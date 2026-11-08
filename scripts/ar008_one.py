"""Run one AR008 task/condition in a fresh process."""

from __future__ import annotations

import argparse
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


async def main(task_id: str, prune: bool, out: str) -> None:
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        task = TASK_BY_ID[task_id]
        rollout = await run_hierarchy(
            env,
            task,
            model,
            tokenizer,
            repair=False,
            max_steps_per_subtask=12,
            semantic=True,
            observation_pruning=prune,
        )
        result = {
            "task_id": task_id,
            "level": task.level,
            "pruning": prune,
            "success": rollout.success,
            "final_progress": rollout.final_progress,
            "steps": rollout.total_steps,
            "prompt_tokens": sum(len(s.prompt_ids) for s in rollout.steps),
            "generated_tokens": sum(len(s.response_ids) for s in rollout.steps),
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--prune", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.task, bool(args.prune), args.out))
