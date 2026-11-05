"""E2: flat adapter routing vs hierarchical decomposition (semantic)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.rollout import rollout_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS, TaskSpec  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ex001"


def route(task: TaskSpec) -> str:
    if task.require_checkout:
        return "checkout"
    if any(qty >= 2 for qty in task.targets.values()):
        return "quantity"
    return "base"


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    results = []
    started = time.time()
    try:
        await env.start()
        for task in EVAL_TASKS:
            model.set_adapter(route(task))
            rollout = await rollout_task(
                env,
                task,
                model,
                tokenizer,
                repair=False,
                sample=False,
                max_steps=12,
                reward_mode="vgdp",
                semantic=True,
            )
            results.append(
                {
                    "task_id": task.task_id,
                    "level": task.level,
                    "success": rollout.success,
                    "final_progress": rollout.final_progress,
                    "steps": rollout.total_steps,
                }
            )
            print(
                f"[flat] {task.task_id}: success={rollout.success} "
                f"phi={rollout.final_progress:.2f} steps={rollout.total_steps}",
                flush=True,
            )
    finally:
        await env.close()
        server.stop()
    count = max(1, len(results))
    summary = {
        "label": "semantic_flat_router",
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "seconds": round(time.time() - started, 2),
        "results": results,
    }
    (OUT / "e2_flat.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False)[:400])


if __name__ == "__main__":
    asyncio.run(main())
