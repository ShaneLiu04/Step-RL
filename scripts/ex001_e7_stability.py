"""E7: repeatability + step/token cost on representative tasks."""

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
from step_rl.edge.tasks import TASK_BY_ID  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
TASKS = ["ev_qty_p3", "ev_checkout_p3", "ev_multi_p3p4"]
OUT = ROOT / "outputs" / "ex001"


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    rows = []
    started = time.time()
    try:
        await env.start()
        for task_id in TASKS:
            task = TASK_BY_ID[task_id]
            for repeat in range(2):
                rollout = await run_hierarchy(
                    env,
                    task,
                    model,
                    tokenizer,
                    repair=False,
                    max_steps_per_subtask=12,
                    semantic=True,
                )
                prompt_tokens = sum(len(step.prompt_ids) for step in rollout.steps)
                gen_tokens = sum(len(step.response_ids) for step in rollout.steps)
                rows.append(
                    {
                        "task_id": task_id,
                        "repeat": repeat,
                        "success": rollout.success,
                        "steps": rollout.total_steps,
                        "prompt_tokens": prompt_tokens,
                        "generated_tokens": gen_tokens,
                    }
                )
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    finally:
        await env.close()
        server.stop()

    per_task = {}
    for task_id in TASKS:
        items = [r for r in rows if r["task_id"] == task_id]
        per_task[task_id] = {
            "success_rate": sum(r["success"] for r in items) / len(items),
            "avg_steps": sum(r["steps"] for r in items) / len(items),
            "avg_prompt_tokens": sum(r["prompt_tokens"] for r in items) / len(items),
            "avg_generated_tokens": sum(r["generated_tokens"] for r in items)
            / len(items),
            "tokens_per_success": (
                sum(r["prompt_tokens"] + r["generated_tokens"] for r in items)
                / max(1, sum(r["success"] for r in items))
            ),
        }
    result = {
        "tasks": TASKS,
        "repeats": 2,
        "seconds": round(time.time() - started, 2),
        "per_task": per_task,
        "rows": rows,
    }
    (OUT / "e7_stability.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(per_task, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
