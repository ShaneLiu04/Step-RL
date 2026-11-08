"""AR008: full vs verifier-guided pruned observations."""

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
OUT = ROOT / "outputs" / "ar008" / "eval"


async def run_condition(model, tokenizer, label: str, prune: bool) -> dict:
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
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
                max_steps_per_subtask=12,
                semantic=True,
                observation_pruning=prune,
            )
            prompt_tokens = sum(len(step.prompt_ids) for step in rollout.steps)
            gen_tokens = sum(len(step.response_ids) for step in rollout.steps)
            results.append(
                {
                    "task_id": task.task_id,
                    "level": task.level,
                    "success": rollout.success,
                    "final_progress": rollout.final_progress,
                    "steps": rollout.total_steps,
                    "prompt_tokens": prompt_tokens,
                    "generated_tokens": gen_tokens,
                }
            )
            print(
                f"[{label}] {task.task_id}: success={rollout.success} "
                f"steps={rollout.total_steps} prompt_tokens={prompt_tokens}",
                flush=True,
            )
    finally:
        await env.close()
        server.stop()
    count = max(1, len(results))
    return {
        "label": label,
        "observation_pruning": prune,
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "prompt_tokens": sum(r["prompt_tokens"] for r in results),
        "generated_tokens": sum(r["generated_tokens"] for r in results),
        "avg_prompt_tokens": sum(r["prompt_tokens"] for r in results) / count,
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
    for label, prune in (("full_observation", False), ("pruned_observation", True)):
        report = await run_condition(model, tokenizer, label, prune)
        reports.append(report)
        (OUT / f"{label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "results"},
                ensure_ascii=False,
            ),
            flush=True,
        )

    lines = [
        "# AR008 观测压缩真实评测",
        "",
        "| 条件 | 成功率 | 平均步数 | Prompt tokens | 生成 tokens | 耗时(s) |",
        "|------|--------|----------|---------------|-------------|---------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['success_rate']:.1%} | "
            f"{report['avg_steps']:.2f} | {report['prompt_tokens']} | "
            f"{report['generated_tokens']} | {report['seconds']} |"
        )
    base = reports[0]["prompt_tokens"]
    pruned = reports[1]["prompt_tokens"]
    reduction = 1 - pruned / max(1, base)
    lines += ["", f"Prompt token reduction: **{reduction:.1%}**", ""]
    (OUT / "ar008_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
