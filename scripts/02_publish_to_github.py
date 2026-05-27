import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"

load_dotenv(ROOT / ".env")

REPO_NAME = os.getenv("GITHUB_REPO_NAME", "arch-research-ai-skill")
VISIBILITY = os.getenv("GITHUB_VISIBILITY", "public")
PUBLISH_PATHS = [
    Path(".gitignore"),
    Path("README.md"),
    Path("SKILL.md"),
    Path("scripts"),
    Path("source"),
    Path("workflow"),
    Path("templates"),
    Path("examples"),
    Path("output/README.md"),
    Path("output/SKILL.md"),
    Path("output/workflow"),
    Path("output/templates"),
    Path("output/examples"),
]


class GitHubAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def run(cmd, check=True):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(f"命令执行失败：{' '.join(cmd)}")

    return result


def run_text(cmd) -> str:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or f"命令执行失败：{' '.join(cmd)}"
        raise RuntimeError(msg)
    return result.stdout.strip()


def git_config_value(key: str) -> str:
    result = run(["git", "config", "--get", key], check=False)
    return result.stdout.strip()


def resolve_git_identity() -> tuple[str, str]:
    name = os.getenv("GIT_USER_NAME") or git_config_value("user.name")
    email = os.getenv("GIT_USER_EMAIL") or git_config_value("user.email")

    if name and email:
        return name, email

    gh_user = run(["gh", "api", "user", "--jq", ".login"], check=False).stdout.strip()
    if gh_user:
        if not name:
            name = gh_user
        if not email:
            email = f"{gh_user}@users.noreply.github.com"

    if not name or not email:
        raise RuntimeError(
            "无法自动确定 Git 提交身份，请先设置 GIT_USER_NAME 和 GIT_USER_EMAIL，"
            "或配置 git user.name / user.email。"
        )

    run(["git", "config", "user.name", name])
    run(["git", "config", "user.email", email])
    print(f"已配置本地 Git 身份：{name} <{email}>")
    return name, email


def github_repo_full_name() -> str:
    return run_text(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])


def github_token() -> str:
    return run_text(["gh", "auth", "token"])


def files_for_publish() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []

    for rel in PUBLISH_PATHS:
        target = ROOT / rel
        if not target.exists():
            continue

        if target.is_file():
            files.append((rel, "100644"))
            continue

        for child in target.rglob("*"):
            if child.is_file():
                child_rel = child.relative_to(ROOT)
                files.append((child_rel, "100644"))

    # 去重并排序，确保发布结果稳定
    dedup = {path.as_posix(): (path, mode) for path, mode in files}
    return [dedup[key] for key in sorted(dedup.keys())]


def head_message() -> str:
    return run_text(["git", "show", "-s", "--format=%B", "HEAD"]).strip()


def github_api(token: str, method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "paper-workflow-publisher",
    }

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubAPIError(f"GitHub API 请求失败：{method} {url}\n{detail}", exc.code) from exc


def publish_via_github_api():
    full_name = github_repo_full_name()
    token = github_token()
    owner, repo = full_name.split("/", 1)

    print("git push 失败，尝试使用 GitHub API 直接发布。")

    ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/main"
    try:
        github_api(token, "GET", ref_url)
    except GitHubAPIError as exc:
        if exc.status_code not in (404, 409):
            raise
        bootstrap_content = base64.b64encode(b"bootstrap\n").decode("ascii")
        github_api(
            token,
            "PUT",
            f"https://api.github.com/repos/{owner}/{repo}/contents/.bootstrap-init.txt",
            {
                "message": "chore: bootstrap repository",
                "content": bootstrap_content,
                "branch": "main",
            },
        )
        print("已创建空仓库自举提交。")

    files = files_for_publish()
    total = len(files)

    if total == 0:
        raise RuntimeError("未找到可发布文件，请先运行 scripts/01_generate_skill.py 生成 output 内容。")

    tree_entries = []
    for idx, (rel_path, mode) in enumerate(files, start=1):
        file_bytes = (ROOT / rel_path).read_bytes()
        blob = github_api(
            token,
            "POST",
            f"https://api.github.com/repos/{owner}/{repo}/git/blobs",
            {
                "content": base64.b64encode(file_bytes).decode("ascii"),
                "encoding": "base64",
            },
        )
        tree_entries.append(
            {
                "path": rel_path.as_posix(),
                "mode": mode,
                "type": "blob",
                "sha": blob["sha"],
            }
        )

        if idx % 25 == 0 or idx == total:
            print(f"已上传文件对象：{idx}/{total}")

    tree = github_api(
        token,
        "POST",
        f"https://api.github.com/repos/{owner}/{repo}/git/trees",
        {"tree": tree_entries},
    )

    parents = []
    try:
        ref_data = github_api(token, "GET", ref_url)
        parents = [ref_data["object"]["sha"]]
    except GitHubAPIError as exc:
        if exc.status_code not in (404, 409):
            raise

    commit_payload = {
        "message": head_message() or "Initial release: architecture research AI skill v0.1",
        "tree": tree["sha"],
    }
    if parents:
        commit_payload["parents"] = parents

    commit = github_api(
        token,
        "POST",
        f"https://api.github.com/repos/{owner}/{repo}/git/commits",
        commit_payload,
    )

    if parents:
        github_api(token, "PATCH", ref_url, {"sha": commit["sha"], "force": True})
    else:
        github_api(
            token,
            "POST",
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            {"ref": "refs/heads/main", "sha": commit["sha"]},
        )

    print(f"已通过 GitHub API 发布到：https://github.com/{full_name}")


def copy_output_to_root():
    if not OUTPUT_DIR.exists():
        raise FileNotFoundError("找不到 output 文件夹，请先运行 scripts/01_generate_skill.py")

    for name in ["README.md", "SKILL.md"]:
        src = OUTPUT_DIR / name
        if src.exists():
            shutil.copy2(src, ROOT / name)

    for folder in ["workflow", "templates", "examples"]:
        src_dir = OUTPUT_DIR / folder
        dst_dir = ROOT / folder

        if dst_dir.exists():
            shutil.rmtree(dst_dir)

        if src_dir.exists():
            shutil.copytree(src_dir, dst_dir)

    gitignore = ROOT / ".gitignore"
    gitignore.write_text(
        ".env\n"
        "__pycache__/\n"
        "*.pyc\n"
        ".DS_Store\n"
        "output/metadata.json\n"
        ".venv/\n",
        encoding="utf-8"
    )

    print("已将 output 内容复制到仓库根目录。")


def init_git_if_needed():
    if not (ROOT / ".git").exists():
        run(["git", "init"])


def commit_files():
    run(["git", "add", "."])
    resolve_git_identity()
    result = run(
        ["git", "commit", "-m", "Initial release: architecture research AI skill v0.1"],
        check=False
    )

    if result.returncode != 0:
        text = f"{result.stdout}\n{result.stderr}"
        if "nothing to commit" in text or "nothing added to commit" in text:
            print("没有新的文件变化，跳过 commit。")
            return
        raise RuntimeError("Git commit 失败，请检查是否仍然没有文件变化，或 Git 配置是否异常。")


def create_github_repo_and_push():
    remote = run(["git", "remote"], check=False)

    if "origin" not in remote.stdout.split():
        visibility_flag = f"--{VISIBILITY}"

        run([
            "gh", "repo", "create", REPO_NAME,
            visibility_flag,
            "--source", ".",
            "--remote", "origin"
        ])
    else:
        print("已存在 origin remote，跳过 gh repo create。")

    run(["git", "branch", "-M", "main"])
    result = run(["git", "push", "-u", "origin", "main"], check=False)
    if result.returncode != 0:
        publish_via_github_api()


def main():
    copy_output_to_root()
    init_git_if_needed()
    commit_files()
    create_github_repo_and_push()

    print("\n完成：仓库已发布到 GitHub。")
    print(f"仓库名：{REPO_NAME}")


if __name__ == "__main__":
    main()