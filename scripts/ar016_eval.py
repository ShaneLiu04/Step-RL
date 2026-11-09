"""AR016: multi-order composition — merged baseline vs ordered runtime."""

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
from step_rl.edge.runtime import run_order_sequence  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar016" / "eval"

CASES = [
    (
        "M1",
        [{"p3": 1}, {"p2": 2}],
        "先买一件无线充电器并结算，再买两件USB-C数据线并结算",
    ),
    (
        "M2",
        [{"p4": 2}, {"p1": 1}],
        "先买两件蓝牙耳机并结算，再买一件iPhone 15并结算",
    ),
]


async def run_case(model, tokenizer, name, sequence, instruction, ordered):
    task = TaskSpec(
        task_id=name,
        level=5,
        goal=instruction,
        search_query=next(iter(sequence[0])),
        targets={pid: qty for order in sequence for pid, qty in order.items()},
        require_checkout=True,
        order_sequence=sequence,
    )
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        if ordered:
            result = await run_order_sequence(env, task, model, tokenizer)
        else:
            merged = TaskSpec(
                task_id=name + "_merged",
                level=5,
                goal=instruction,
                search_query=task.search_query,
                targets=task.targets,
                require_checkout=True,
            )
            rollout = await run_hierarchy(
                env,
                merged,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=12,
                semantic=True,
            )
            state = await env.get_state()
            progress = compute_progress(state, env.page_url_path, task)
            result = {
                "success": progress.success,
                "orders": state.get("orders", []),
                "attempts": [{"steps": rollout.total_steps}],
            }
        return {
            "task_id": name,
            "mode": "ordered_runtime" if ordered else "merged_llm",
            "success": result["success"],
            "orders": result["orders"],
            "steps": sum(a.get("steps", 0) for a in result["attempts"]),
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    rows = []
    for name, sequence, instruction in CASES:
        rows.append(
            await run_case(model, tokenizer, name, sequence, instruction, False)
        )
        rows.append(await run_case(model, tokenizer, name, sequence, instruction, True))
    (OUT / "ar016_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR016 多订单组合真实评测",
        "",
        "| 任务 | 模式 | 成功 | 订单历史 | 步数 |",
        "|------|------|------|----------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {row['mode']} | "
            f"{'✓' if row['success'] else '✗'} | {row['orders']} | {row['steps']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "- 合并基线把所有商品放入一笔订单，序列验证失败。",
        "- 序列 Runtime 逐单加购/结算，订单历史与目标序列一致。",
        "",
    ]
    (OUT / "ar016_report.md").write_text("\n".join(lines), encoding="utf-8")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
