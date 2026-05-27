import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "source" / "paper_workflow_notes.md"
OUTPUT_DIR = ROOT / "output"

load_dotenv(ROOT / ".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL", "gpt-5.5")


def read_source_notes() -> str:
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"找不到原始笔记文件：{SOURCE_FILE}")
    text = SOURCE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("原始笔记是空的，请先填写 source/paper_workflow_notes.md")
    return text


def extract_json(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("模型输出中没有找到 JSON 对象。")

    json_text = text[start:end + 1]
    return json.loads(json_text)


def build_fallback_package(notes: str) -> dict:
    note_summary = notes[:400].strip()

    workflow_files = [
        {
            "filename": "01_research_question_diagnosis.md",
            "content": "# Research Question Diagnosis\n\n- 梳理论文主题、对象、问题意识。\n- 区分 Human-only、AI-assisted、AI-executable 任务。\n- 输出：研究问题草案、边界与风险清单。\n"
        },
        {
            "filename": "02_literature_screening.md",
            "content": "# Literature Screening\n\n- 建立文献筛选标准。\n- 记录纳入/排除理由。\n- 输出：可追溯的文献筛选表。\n"
        },
        {
            "filename": "03_theory_and_method_fit.md",
            "content": "# Theory and Method Fit\n\n- 检查理论框架与方法是否匹配。\n- 标注方法适配风险。\n- 输出：方法选择说明。\n"
        },
        {
            "filename": "04_outline_and_argument.md",
            "content": "# Outline and Argument\n\n- 组织章节结构与论证链条。\n- 检查每一节是否服务核心问题。\n- 输出：三级提纲与论证地图。\n"
        },
        {
            "filename": "05_evidence_and_figures.md",
            "content": "# Evidence and Figures\n\n- 归档证据、图表与来源。\n- 保证图文对应关系可追踪。\n- 输出：图版任务表与证据台账。\n"
        },
        {
            "filename": "06_submission_checklist.md",
            "content": "# Submission Checklist\n\n- 检查格式、引用、表达与合规性。\n- 避免夸大结论与不实表述。\n- 输出：投稿前核查清单。\n"
        },
    ]

    template_files = [
        {
            "filename": "research_question_canvas.md",
            "content": "# Research Question Canvas\n\n- Topic:\n- Research gap:\n- Core question:\n- Method fit:\n- Risks:\n"
        },
        {
            "filename": "evidence_tracking_template.md",
            "content": "# Evidence Tracking Template\n\n| Item | Source | Note | Status |\n| --- | --- | --- | --- |\n"
        },
        {
            "filename": "submission_review_template.md",
            "content": "# Submission Review Template\n\n- Title:\n- Journal fit:\n- Main contribution:\n- Missing evidence:\n- Compliance check:\n"
        },
    ]

    example_files = [
        {
            "filename": "example_from_paper_workflow.md",
            "content": f"# Example From Paper Workflow\n\n## Source Notes Snapshot\n\n{note_summary}\n"
        }
    ]

    return {
        "readme": "# Paper Workflow Skill\n\nA pragmatic workflow package for turning thesis-writing notes into reusable AI-assisted research operations.\n",
        "skill": "# SKILL\n\nThis skill supports research workflow planning, evidence tracking, outline drafting, and submission checks. AI is used for assistance, not for replacing academic judgment.\n",
        "workflow_files": workflow_files,
        "template_files": template_files,
        "example_files": example_files,
        "repo_description": "A reusable workflow skill for academic paper planning and verification.",
        "xiaohongshu_summary": "先把论文写作流程拆成可执行的小步骤，方便后面逐步补证、核查和整理。",
    }


def generate_skill_package(notes: str) -> dict:
    prompt = f"""
你是一个“科研 AI 工作流 Skill”设计专家。

请根据用户提供的真实论文写作流程笔记，整理成一个可以发布到 GitHub 的 Skill 仓库内容。

重要定位：
- 领域：建筑学、城乡规划、人居环境、设计学相关中文期刊论文写作。
- 用户：硕士、博士、博士后、青年教师。
- 目标：帮助研究者把论文写作流程拆解成 AI 可协作、可校验、可复用的工作流。
- 绝对不要宣传 AI 代写论文。
- 必须强调：AI 不替代科学问题判断、学术贡献判断、方法适配判断、数据真实性判断。
- 必须明确区分 Human-only、AI-assisted、AI-executable 三类任务。

禁止出现以下表达：
- AI代写论文
- 保证发表
- 快速发核心
- 不需要阅读文献
- 不需要导师
- 一键成稿
- 自动完成科研

请输出严格 JSON，不要输出 JSON 以外的任何解释。

JSON 结构如下：

{{
  "readme": "README.md 的完整 Markdown 内容",
  "skill": "SKILL.md 的完整 Markdown 内容",
  "workflow_files": [
    {{
      "filename": "01_research_idea_diagnosis.md",
      "content": "Markdown 内容"
    }}
  ],
  "template_files": [
    {{
      "filename": "research_question_canvas.md",
      "content": "Markdown 内容"
    }}
  ],
  "example_files": [
    {{
      "filename": "example_from_paper_workflow.md",
      "content": "Markdown 内容"
    }}
  ],
  "repo_description": "一句话仓库简介",
  "xiaohongshu_summary": "适合发小红书的简短说明，保持个人记录口吻，不要像卖课"
}}

请至少生成：
- 1 个 README.md
- 1 个 SKILL.md
- 6 个 workflow 文件
- 3 个 template 文件
- 1 个 example 文件

原始论文流程笔记如下：

---
{notes}
---
"""

    try:
        response = client.responses.create(
            model=MODEL,
            input=prompt,
            store=False,
        )
        return extract_json(response.output_text)
    except Exception as exc:
        print(f"警告：在线生成失败，已切换为本地降级草稿。原因：{exc}")
        return build_fallback_package(notes)


def safe_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"已生成：{path.relative_to(ROOT)}")


def write_package(package: dict):
    OUTPUT_DIR.mkdir(exist_ok=True)

    safe_write(OUTPUT_DIR / "README.md", package["readme"])
    safe_write(OUTPUT_DIR / "SKILL.md", package["skill"])

    for item in package.get("workflow_files", []):
        safe_write(OUTPUT_DIR / "workflow" / item["filename"], item["content"])

    for item in package.get("template_files", []):
        safe_write(OUTPUT_DIR / "templates" / item["filename"], item["content"])

    for item in package.get("example_files", []):
        safe_write(OUTPUT_DIR / "examples" / item["filename"], item["content"])

    metadata = {
        "repo_description": package.get("repo_description", ""),
        "xiaohongshu_summary": package.get("xiaohongshu_summary", "")
    }

    safe_write(
        OUTPUT_DIR / "metadata.json",
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )


def main():
    notes = read_source_notes()
    package = generate_skill_package(notes)
    write_package(package)

    print("\n完成：Skill 初稿已生成在 output/ 文件夹。")
    print("下一步：请人工检查 README.md 和 SKILL.md，确认没有虚构案例、虚构文献或过度承诺。")


if __name__ == "__main__":
    main()