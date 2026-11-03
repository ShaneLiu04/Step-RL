"""Evaluate the composed (routed) policy on all held-out tasks.

Routes by deployment-known task metadata:
  L1/L2 -> SFT
  L3    -> VGDP adapter (learned quantity control)
  L4/L5 -> Sparse adapter (preserves checkout flow)

The router is persisted in step_rl/edge/router.py and never uses gold labels.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.evaluate import evaluate_policy  # noqa: E402
from step_rl.edge.router import route_adapter  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar001/sft_adapter",
    "quantity": "outputs/ar001/grpo_vgdp",
    "checkout": "outputs/ar001/grpo_sparse",
}


def _merge(label: str, groups: dict) -> dict:
    results = []
    for summary in groups.values():
        results.extend(summary["results"])
    count = max(1, len(results))
    return {
        "label": label,
        "repair": True,
        "adapter": "routed:" + ",".join(sorted(ADAPTERS)),
        "model": next(iter(groups.values()))["model"],
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "raw_invalid_rate": sum(1 for r in results if r["raw_invalid"] > 0) / count,
        "repair_rate": sum(1 for r in results if r["repaired"] > 0) / count,
        "seconds": sum(s["seconds"] for s in groups.values()),
        "results": sorted(results, key=lambda r: r["task_id"]),
    }


def _render(summary: dict) -> str:
    lines = [
        "# AR001 组合路由评测",
        "",
        f"- 组合：`{summary['label']}`",
        f"- 适配器：`{summary['adapter']}`",
        f"- 任务数：{summary['tasks']}",
        f"- 成功率：{summary['success_rate']:.1%}",
        f"- 平均步数：{summary['avg_steps']:.2f}",
        f"- 平均进度：{summary['avg_progress']:.2f}",
        "",
        "| 任务 | 成功 | 进度 | 步数 |",
        "|------|------|------|------|",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['task_id']} | {'✓' if r['success'] else '✗'} | "
            f"{r['final_progress']:.2f} | {r['steps']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    groups = defaultdict(list)
    for task in EVAL_TASKS:
        groups[route_adapter(task, ADAPTERS)].append(task)

    summaries = {}
    for key, tasks in groups.items():
        summaries[key] = asyncio.run(
            evaluate_policy(
                f"router_{key}",
                ADAPTERS[key],
                repair=True,
                tasks=tasks,
                max_steps=8,
            )
        )

    merged = _merge("routed_combo_repair", summaries)
    out = ROOT / "outputs" / "ar001" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "router.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "router.md").write_text(_render(merged), encoding="utf-8")
    print(_render(merged))


if __name__ == "__main__":
    main()
