"""AR007: closed-loop replanning under checkout-time environment drift."""

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
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.supervisor import run_supervised  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar007" / "eval"

DYNAMIC = [
    {
        "name": "D1_stock_substitution",
        "instruction": "买两件蓝牙耳机；如果缺货，就买两件USB-C数据线，并结算",
        "expected": {"p2": 2},
        "server": {"checkout_stock_drop": {"p4": 1}},
    },
    {
        "name": "D2_price_budget",
        "instruction": "预算300元，买无线充电器；如果超预算，就买USB-C数据线，并结算",
        "expected": {"p2": 1},
        "server": {
            "checkout_price_override": {"p3": 350},
            "checkout_budget": 300,
        },
    },
]

STATIC = [
    "买最便宜的商品并完成结算",
    "买两件USB-C数据线并结算",
    "预算650元，买无线充电器和蓝牙耳机各一件，并结算",
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


async def run_case(model, tokenizer, scenario, mode):
    server = LocalShopServer(**scenario.get("server", {})).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = expected_spec(scenario["instruction"], scenario["expected"], catalog)
        await env.start()
        if mode == "baseline":
            planned = plan_instruction(scenario["instruction"], catalog)
            rollout = await run_hierarchy(
                env,
                planned,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=12,
                semantic=True,
            )
            state = await env.get_state()
            success = compute_progress(state, env.page_url_path, spec).success
            result = {
                "planned": dict(planned.targets),
                "attempts": 1,
                "replanned": False,
                "success": success,
                "steps": rollout.total_steps,
            }
        else:
            sup = await run_supervised(
                env,
                scenario["instruction"],
                model,
                tokenizer,
                max_steps_per_subtask=12,
            )
            state = await env.get_state()
            success = compute_progress(state, env.page_url_path, spec).success
            result = {
                "planned": sup["spec"],
                "attempts": len(sup["attempts"]),
                "replanned": sup["replanned"],
                "success": success,
                "steps": sum(a["steps"] for a in sup["attempts"]),
                "attempt_targets": [a["targets"] for a in sup["attempts"]],
            }
    finally:
        await env.close()
        server.stop()
    result.update(
        {
            "scenario": scenario["name"],
            "mode": mode,
            "seconds": round(time.time() - started, 2),
        }
    )
    return result


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    results = []
    for scenario in DYNAMIC:
        for mode in ("baseline", "supervisor"):
            result = await run_case(model, tokenizer, scenario, mode)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            results.append(result)

    # Static regression: supervisor must succeed on first attempt.
    for instruction in STATIC:
        scenario = {
            "name": "static:" + instruction[:12],
            "instruction": instruction,
            "expected": None,
            "server": {},
        }
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            catalog = fetch_catalog(server.base_url)
            spec = plan_instruction(instruction, catalog)
            scenario["expected"] = dict(spec.targets)
            await env.start()
            sup = await run_supervised(
                env, instruction, model, tokenizer, max_steps_per_subtask=12
            )
            exp = expected_spec(instruction, spec.targets, catalog)
            state = await env.get_state()
            ok = compute_progress(state, env.page_url_path, exp).success
            results.append(
                {
                    "scenario": scenario["name"],
                    "mode": "supervisor_static",
                    "planned": sup["spec"],
                    "attempts": len(sup["attempts"]),
                    "replanned": sup["replanned"],
                    "success": ok,
                    "steps": sum(a["steps"] for a in sup["attempts"]),
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        finally:
            await env.close()
            server.stop()

    (OUT / "ar007_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR007 闭环重规划真实评测",
        "",
        "| 场景 | 模式 | 成功 | 尝试 | 重规划 | 步数 |",
        "|------|------|------|------|--------|------|",
    ]
    for r in results:
        lines.append(
            f"| {r['scenario']} | {r['mode']} | {'✓' if r['success'] else '✗'} | "
            f"{r['attempts']} | {'是' if r['replanned'] else '否'} | {r['steps']} |"
        )
    lines.append("")
    (OUT / "ar007_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
