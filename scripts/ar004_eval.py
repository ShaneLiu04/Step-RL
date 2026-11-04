"""AR004: semantic Set-of-Mark interface under DOM id churn."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.hierarchical import run_hierarchy  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar004" / "eval"


async def run_condition(model, tokenizer, label: str, perturb: bool) -> dict:
    server = LocalShopServer().start()
    env = BrowserEnv(
        server,
        channel="msedge",
        headless=True,
        semantic=True,
        perturb_ids=perturb,
    )
    results = []
    started = time.time()
    try:
        await env.start()
        for task in EVAL_TASKS:
            rollout = await run_hierarchy(
                env,
                task,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=8,
                semantic=True,
            )
            results.append(
                {
                    "task_id": task.task_id,
                    "level": task.level,
                    "success": rollout.success,
                    "final_progress": rollout.final_progress,
                    "steps": rollout.total_steps,
                    "raw_invalid": rollout.raw_invalid,
                    "repaired": rollout.repaired,
                }
            )
            print(
                f"[{label}] {task.task_id}: success={rollout.success} "
                f"phi={rollout.final_progress:.2f} steps={rollout.total_steps}",
                flush=True,
            )
    finally:
        await env.close()
        server.stop()
    count = max(1, len(results))
    return {
        "label": label,
        "perturb_ids": perturb,
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "raw_invalid": sum(r["raw_invalid"] for r in results),
        "repaired": sum(r["repaired"] for r in results),
        "seconds": round(time.time() - started, 2),
        "results": results,
    }


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    reports = []
    for label, perturb in (
        ("semantic_stable", False),
        ("semantic_id_churn", True),
    ):
        report = await run_condition(model, tokenizer, label, perturb)
        reports.append(report)
        (OUT / f"{label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "results"},
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

    lines = [
        "# AR004 语义 Set-of-Mark 真实评测",
        "",
        "| 条件 | ID 扰动 | 成功率 | 平均步数 | 平均进度 | 非法动作 | 修复 |",
        "|------|---------|--------|----------|----------|----------|------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {'是' if report['perturb_ids'] else '否'} | "
            f"{report['success_rate']:.1%} | {report['avg_steps']:.2f} | "
            f"{report['avg_progress']:.2f} | {report['raw_invalid']} | "
            f"{report['repaired']} |"
        )
    lines.append("")
    (OUT / "ar004_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
