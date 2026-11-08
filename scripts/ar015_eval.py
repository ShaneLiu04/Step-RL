"""AR015: cart quantity update — LLM baseline vs extended skill."""

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
from step_rl.edge.skill_library import run_skill_hierarchy  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar015" / "eval"

TASKS = [
    TaskSpec(
        task_id="up_p3_1to3",
        level=2,
        goal="把购物车中的无线充电器数量改为3",
        search_query="无线",
        targets={"p3": 3},
        seed_cart={"p3": 1},
        operation="update",
        predicates=["cart_quantity_exact"],
        exact_quantity=True,
    ),
    TaskSpec(
        task_id="up_p4_2to4",
        level=2,
        goal="把购物车中的蓝牙降噪耳机数量改为4",
        search_query="蓝牙",
        targets={"p4": 4},
        seed_cart={"p4": 2},
        operation="update",
        predicates=["cart_quantity_exact"],
        exact_quantity=True,
    ),
    TaskSpec(
        task_id="up_p3_3to1",
        level=2,
        goal="把购物车中的无线充电器数量改为1",
        search_query="无线",
        targets={"p3": 1},
        seed_cart={"p3": 3},
        operation="update",
        predicates=["cart_quantity_exact"],
        exact_quantity=True,
    ),
]


async def run_case(model, tokenizer, task, skill: bool):
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        if skill:
            rollout = await run_skill_hierarchy(
                env,
                task,
                model,
                tokenizer,
                fallback=False,
                semantic=True,
            )
        else:
            rollout = await run_hierarchy(
                env,
                task,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=12,
                semantic=True,
            )
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, task)
        return {
            "task_id": task.task_id,
            "mode": "skill" if skill else "baseline_llm",
            "success": progress.success,
            "cart": final.get("cart"),
            "steps": rollout.total_steps,
            "policy_steps": sum(1 for s in rollout.steps if s.source == "policy"),
            "skill_steps": sum(1 for s in rollout.steps if s.source == "skill"),
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
    for task in TASKS:
        rows.append(await run_case(model, tokenizer, task, skill=False))
        rows.append(await run_case(model, tokenizer, task, skill=True))
    (OUT / "ar015_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR015 购物车数量更新真实评测",
        "",
        "| 任务 | 模式 | 成功 | 购物车 | LLM 步 | 技能步 | 耗时 |",
        "|------|------|------|--------|--------|--------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {row['mode']} | "
            f"{'✓' if row['success'] else '✗'} | {row['cart']} | "
            f"{row['policy_steps']} | {row['skill_steps']} | {row['seconds']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "- 基线为 LLM 层级；技能为真实演示动作参数化的 update_quantity。",
        "- 成功按精确购物车数量判定；失败或收益不足均如实记录。",
        "",
    ]
    (OUT / "ar015_report.md").write_text("\n".join(lines), encoding="utf-8")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
