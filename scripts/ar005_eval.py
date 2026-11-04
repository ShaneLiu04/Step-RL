"""AR005: zero-shot cross-layout transfer of semantic actions."""

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

SEMANTIC = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
SELECTOR = {
    "base": "outputs/ar001/sft_adapter",
    "quantity": "outputs/ar001/grpo_vgdp",
    "checkout": "outputs/ar001/grpo_sparse",
}
OUT = ROOT / "outputs" / "ar005" / "eval"


async def run_condition(
    label: str, adapters: dict, semantic: bool, layout: str, perturb: bool = False
) -> dict:
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), adapters)
    server = LocalShopServer(layout=layout).start()
    env = BrowserEnv(
        server,
        channel="msedge",
        headless=True,
        semantic=semantic,
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
                repair=not semantic,
                max_steps_per_subtask=12,
                semantic=semantic,
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
        "layout": layout,
        "semantic": semantic,
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
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for label, adapters, semantic, layout in (
        ("semantic_v1", SEMANTIC, True, "v1", False),
        ("semantic_v2_zero_shot", SEMANTIC, True, "v2", False),
        ("selector_v2", SELECTOR, False, "v2", False),
        ("semantic_v2_churn", SEMANTIC, True, "v2", True),
        ("selector_v2_churn", SELECTOR, False, "v2", True),
    ):
        report = await run_condition(label, adapters, semantic, layout, perturb)
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
        "# AR005 跨布局零样本迁移评测",
        "",
        "| 条件 | 布局 | 接口 | 成功率 | 平均步数 | 平均进度 | 非法动作 |",
        "|------|------|------|--------|----------|----------|----------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['layout']} | "
            f"{'semantic' if report['semantic'] else 'selector'} | "
            f"{report['success_rate']:.1%} | {report['avg_steps']:.2f} | "
            f"{report['avg_progress']:.2f} | {report['raw_invalid']} |"
        )
    lines.append("")
    (OUT / "ar005_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
