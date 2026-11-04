"""AR003: evaluate verifier-guided hierarchical task decomposition."""

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
    "base": "outputs/ar001/sft_adapter",
    "quantity": "outputs/ar001/grpo_vgdp",
    "checkout": "outputs/ar001/grpo_sparse",
}
OUT = ROOT / "outputs" / "ar003" / "eval"


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True)
    results = []
    started = time.time()
    try:
        await env.start()
        for task in EVAL_TASKS:
            rollout = await run_hierarchy(
                env, task, model, tokenizer, repair=True, max_steps_per_subtask=8
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
                    "sources": [step.source for step in rollout.steps],
                }
            )
            print(
                f"[hierarchy] {task.task_id}: success={rollout.success} "
                f"phi={rollout.final_progress:.2f} steps={rollout.total_steps}",
                flush=True,
            )
    finally:
        await env.close()
        server.stop()

    count = max(1, len(results))
    summary = {
        "label": "hierarchical_combo_repair",
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "seconds": round(time.time() - started, 2),
        "results": results,
    }
    (OUT / "hierarchical.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
