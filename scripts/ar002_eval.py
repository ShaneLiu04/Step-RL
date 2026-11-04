"""AR002: evaluate router + skill memory + verifier-triggered replanning."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.evaluate import evaluate_policy  # noqa: E402
from step_rl.edge.skill_memory import SkillMemory  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS, TASK_BY_ID  # noqa: E402

BASE_REPORT = ROOT / "outputs" / "ar001" / "eval" / "router.json"
OUT = ROOT / "outputs" / "ar002" / "eval"
MEMORY = ROOT / "step_rl" / "edge" / "skill_memory.json"
SPARSE = "outputs/ar001/grpo_sparse"

CHECKOUT_TASKS = [t for t in EVAL_TASKS if t.require_checkout]


def _merge(label: str, base: dict, variant: dict) -> dict:
    base_results = [
        r for r in base["results"] if not TASK_BY_ID[r["task_id"]].require_checkout
    ]
    results = base_results + variant["results"]
    count = max(1, len(results))
    return {
        "label": label,
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "memory_replans": sum(r.get("memory_replans", 0) for r in results),
        "results": sorted(results, key=lambda r: r["task_id"]),
    }


def _render(reports: list[dict]) -> str:
    lines = [
        "# AR002 记忆与重规划真实评测",
        "",
        "| 组合 | 成功率 | 平均步数 | 平均进度 | 重规划次数 |",
        "|------|--------|----------|----------|------------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['success_rate']:.1%} | "
            f"{report['avg_steps']:.2f} | {report['avg_progress']:.2f} | "
            f"{report.get('memory_replans', 0)} |"
        )
    best = max(reports, key=lambda r: (r["success_rate"], r["avg_progress"]))
    lines += [
        "",
        f"最优组合：**{best['label']}**（成功率 {best['success_rate']:.1%}）",
        "",
        "## 逐任务（L4/L5）",
        "",
        "| 任务 | 组合 | 成功 | 进度 | 步数 | 重规划 |",
        "|------|------|------|------|------|--------|",
    ]
    for report in reports:
        for item in report["results"]:
            if not TASK_BY_ID[item["task_id"]].require_checkout:
                continue
            lines.append(
                f"| {item['task_id']} | {report['label']} | "
                f"{'✓' if item['success'] else '✗'} | "
                f"{item['final_progress']:.2f} | {item['steps']} | "
                f"{item.get('memory_replans', 0)} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    base = json.loads(BASE_REPORT.read_text(encoding="utf-8"))
    memory = SkillMemory.load(MEMORY)

    reports = [base]
    for label, prompt, replan in (
        ("router_memory", True, False),
        ("router_replan", True, True),
    ):
        variant = asyncio.run(
            evaluate_policy(
                label,
                SPARSE,
                repair=True,
                tasks=CHECKOUT_TASKS,
                max_steps=8,
                memory=memory,
                memory_prompt=prompt,
                replan=replan,
            )
        )
        merged = _merge(label, base, variant)
        (OUT / f"{label}.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reports.append(merged)
        print(
            f"[eval] {label}: success={merged['success_rate']:.3f} "
            f"steps={merged['avg_steps']:.2f} replans={merged['memory_replans']}",
            flush=True,
        )

    (OUT / "ar002_report.json").write_text(
        json.dumps({"reports": reports}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    text = _render(reports)
    (OUT / "ar002_report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
