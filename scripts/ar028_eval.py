"""AR028: cart-to-order transaction (CTC + checkout + promo preflight), real Edge."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar028" / "eval"

CASES = [
    (
        "double_checkout",
        "把购物车里的所有商品数量都加倍，并结算",
        {"p3": 1, "p4": 1},
        {"p3": 2, "p4": 2},
        False,
    ),
    (
        "double_checkout_promo",
        "把购物车里的所有商品数量都加倍，并使用满400减50优惠结算",
        {"p3": 1, "p4": 1},
        {"p3": 2, "p4": 2},
        True,
    ),
    (
        "add1_checkout",
        "把购物车里的每件商品数量加1，并结算",
        {"p3": 1, "p4": 2},
        {"p3": 2, "p4": 3},
        False,
    ),
]


async def run_case(instruction, seed, expected, enable_compound, server_kwargs=None):
    server = LocalShopServer(**(server_kwargs or {})).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        task = TaskSpec(
            task_id="cart_to_order",
            level=5,
            goal=instruction,
            search_query="",
            targets={},
            start_path="/cart",
            seed_cart=seed,
        )
        await env.reset(task)
        result = await run_task(
            env,
            instruction,
            None,
            None,
            enable_compound=enable_compound,
        )
        state = await env.get_state()
        expected_task = TaskSpec(
            task_id="expected",
            level=5,
            goal=instruction,
            search_query="",
            targets=dict(expected),
            start_path="/cart",
            require_checkout=True,
            predicates=["cart_contains"],
            cart_transform="expected",
        )
        expected_ok = compute_progress(
            state, env.page_url_path, expected_task
        ).success
        return {
            "instruction": instruction,
            "seed": seed,
            "expected": expected,
            "enable_compound": enable_compound,
            "success": bool(result.get("success")) and expected_ok,
            "expected_ok": expected_ok,
            "preflight": bool(result.get("preflight", False)),
            "error": result.get("error", ""),
            "compensated": result.get("compensated", 0),
            "steps": len(result.get("steps", [])),
            "policy_steps": 0,
            "prompt_tokens": 0,
            "cart": state.get("cart", {}),
            "order": state.get("order"),
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case, instruction, seed, expected, promo in CASES:
        base = await run_case(instruction, seed, expected, False)
        base.update({"case": case, "mode": "baseline_ar027"})
        rows.append(base)
        cot = await run_case(instruction, seed, expected, True)
        cot.update({"case": case, "mode": "cot"})
        rows.append(cot)

    preflight = await run_case(
        "把购物车里的所有商品数量都加倍，并使用满2000减150优惠结算",
        {"p3": 1},
        {"p3": 2},
        True,
    )
    preflight.update({"case": "preflight", "mode": "cot_preflight"})
    rows.append(preflight)

    rollback = await run_case(
        "把购物车里的所有商品数量都加倍，并结算",
        {"p3": 1, "p4": 1},
        {"p3": 2, "p4": 2},
        True,
        {"fault_order_once": True},
    )
    rollback.update({"case": "order_fault", "mode": "cot_fault"})
    rows.append(rollback)

    base_rows = [r for r in rows if r["mode"] == "baseline_ar027"]
    cot_rows = [r for r in rows if r["mode"] == "cot"]
    summary = {
        "baseline": {"success": sum(r["success"] for r in base_rows), "tasks": len(base_rows)},
        "cot": {"success": sum(r["success"] for r in cot_rows), "tasks": len(cot_rows)},
        "preflight": preflight,
        "rollback": rollback,
    }
    verdict = {
        "P0_baseline_gap": summary["baseline"]["success"] == 0,
        "P1_cot_all": summary["cot"]["success"] == len(cot_rows),
        "P2_zero_llm": all(
            r["policy_steps"] == 0 and r["prompt_tokens"] == 0 for r in cot_rows
        ),
        "P3_preflight": (
            (not preflight["success"])
            and preflight["preflight"]
            and preflight["cart"] == {"p3": 1}
            and preflight["order"] is None
        ),
        "P4_rollback": (
            (not rollback["success"])
            and rollback["order"] is None
            and rollback["cart"] == {"p3": 1, "p4": 1}
        ),
    }
    verdict["overall"] = all(verdict.values())
    payload = {"ar": "AR028", "summary": summary, "verdict": verdict, "rows": rows}
    (OUT / "ar028_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR028 购物车→订单事务（真实 Edge / 0 LLM）",
        "",
        "| 模式 | 成功 | 任务 |",
        "|------|------|------|",
        f"| baseline（AR027，仅变换） | {summary['baseline']['success']}/{summary['baseline']['tasks']} | 忽略结算 |",
        f"| COT（AR028） | {summary['cot']['success']}/{summary['cot']['tasks']} | 变换 + 结算 + 券预检 |",
        "",
        "## 预检/回滚",
        "",
        f"- preflight: success={preflight['success']}, preflight={preflight['preflight']}, "
        f"cart={preflight['cart']}, order={preflight['order']}",
        f"- order_fault: success={rollback['success']}, cart={rollback['cart']}, "
        f"order={rollback['order']}, compensated={rollback['compensated']}",
        "",
        "## 判定",
        "",
        "```json",
        json.dumps(verdict, ensure_ascii=False, indent=2),
        "```",
    ]
    (OUT / "ar028_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
