"""AR011: unified runtime across 30 real scenarios."""

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
from step_rl.edge.planner import fetch_catalog  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import PRODUCTS, LocalShopServer  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS, TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar011" / "eval"

CONSTRAINT = [
    ("买最便宜的商品并完成结算", {"p2": 1}, {}),
    ("买价格不超过300元的最贵商品并结算", {"p3": 1}, {}),
    ("买两件USB-C数据线并结算", {"p2": 2}, {}),
    ("买一件iPhone 15和两件数据线，完成结算", {"p1": 1, "p2": 2}, {}),
    ("预算650元，买无线充电器和蓝牙耳机各一件，并结算", {"p3": 1, "p4": 1}, {}),
    ("买三件蓝牙耳机并结算", {"p4": 3}, {}),
    ("买最贵的商品并结算", {"p1": 1}, {}),
    ("如果无线充电器缺货，就买蓝牙耳机，并结算", {"p4": 1}, {"p3": 0}),
]
DYNAMIC = [
    (
        "买两件蓝牙耳机；如果缺货，就买两件USB-C数据线，并结算",
        {"p2": 2},
        {"checkout_stock_drop": {"p4": 1}},
    ),
    (
        "预算300元，买无线充电器；如果超预算，就买USB-C数据线，并结算",
        {"p2": 1},
        {"checkout_price_override": {"p3": 350}, "checkout_budget": 300},
    ),
]
ERROR = [
    ("买一件无线充电器并结算", {"p3": 1}),
    ("买两件USB-C数据线并结算", {"p2": 2}),
]


def expected_spec(instruction, expected, catalog):
    first = next((c for c in catalog if c.pid in expected), catalog[0])
    return TaskSpec(
        task_id="expected",
        level=5 if len(expected) > 1 else 4,
        goal=instruction,
        search_query=first.keywords[0] if first.keywords else first.name,
        targets=dict(expected),
        require_checkout=True,
    )


def instruction_for(task):
    if task.level == 1:
        product = PRODUCTS[next(iter(task.targets))]
        return f"搜索{product.keywords[0]}"
    parts = []
    for pid, qty in task.targets.items():
        parts.append(f"买{qty}件{PRODUCTS[pid].name}")
    text = "，".join(parts)
    if task.require_checkout:
        text += "，并结算"
    return text


async def run_case(
    model,
    tokenizer,
    instruction,
    expected,
    server_kwargs,
    layout,
    perturb,
    expected_task=None,
):
    server = LocalShopServer(layout=layout, **server_kwargs).start()
    env = BrowserEnv(
        server, channel="msedge", headless=True, semantic=True, perturb_ids=perturb
    )
    started = time.time()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = (
            expected_task
            if expected_task is not None
            else expected_spec(instruction, expected, catalog)
        )
        await env.start()
        result = await run_task(env, instruction, model, tokenizer)
        state = await env.get_state()
        success = compute_progress(state, env.page_url_path, spec).success
        return {
            "instruction": instruction,
            "expected": expected,
            "layout": layout,
            "perturb_ids": perturb,
            "success": success,
            "attempts": len(result["attempts"]),
            "fallback": result["fallback"],
            "steps": len(result["steps"]),
            "policy_steps": sum(
                1 for step in result["steps"] if step.source == "policy"
            ),
            "skill_steps": sum(1 for step in result["steps"] if step.source == "skill"),
            "prompt_tokens": sum(len(step.prompt_ids) for step in result["steps"]),
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

    for task in EVAL_TASKS:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction_for(task),
                dict(task.targets),
                {},
                "v1",
                False,
                expected_task=task,
            )
        )
    for instruction, expected, stock in CONSTRAINT:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction,
                expected,
                {"stock_overrides": stock} if stock else {},
                "v1",
                False,
            )
        )
    for instruction, expected, server_kwargs in DYNAMIC:
        rows.append(
            await run_case(
                model, tokenizer, instruction, expected, server_kwargs, "v1", False
            )
        )
    for instruction, expected in ERROR:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction,
                expected,
                {
                    "checkout_name_requires_title": True,
                    "checkout_address_requires_road": True,
                },
                "v1",
                False,
            )
        )
    for task in EVAL_TASKS:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction_for(task),
                dict(task.targets),
                {},
                "v2",
                True,
                expected_task=task,
            )
        )

    (OUT / "ar011_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    count = max(1, len(rows))
    summary = {
        "tasks": len(rows),
        "success_rate": sum(r["success"] for r in rows) / count,
        "policy_steps": sum(r["policy_steps"] for r in rows),
        "skill_steps": sum(r["skill_steps"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "seconds": sum(r["seconds"] for r in rows),
    }
    (OUT / "ar011_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR011 统一运行时组合评测（30 场景）",
        "",
        f"- 成功率：{summary['success_rate']:.1%}",
        f"- LLM 调用步数：{summary['policy_steps']}",
        f"- 技能步数：{summary['skill_steps']}",
        f"- Prompt tokens：{summary['prompt_tokens']}",
        f"- 总耗时：{summary['seconds']:.1f}s",
        "",
        "## 逐场景",
        "",
        "| 指令 | 布局 | churn | 成功 | 尝试 | 回退 | LLM 步 | 技能步 |",
        "|------|------|-------|------|------|------|--------|--------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['instruction'][:32]} | {row['layout']} | "
            f"{'是' if row['perturb_ids'] else '否'} | "
            f"{'✓' if row['success'] else '✗'} | {row['attempts']} | "
            f"{'是' if row['fallback'] else '否'} | {row['policy_steps']} | "
            f"{row['skill_steps']} |"
        )
    (OUT / "ar011_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
