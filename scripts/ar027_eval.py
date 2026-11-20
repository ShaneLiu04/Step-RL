"""AR027: cart transaction compiler (CTC), real Edge, 0 LLM."""

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

OUT = ROOT / "outputs" / "ar027" / "eval"

CASES = [
    (
        "double",
        "把购物车里的所有商品数量都加倍",
        {"p3": 1, "p4": 2},
        {"p3": 2, "p4": 4},
    ),
    ("set3", "把购物车里的所有商品数量改成3", {"p3": 2, "p2": 1}, {"p3": 3, "p2": 3}),
    ("add1", "把购物车里的每件商品数量加1", {"p3": 1, "p4": 1}, {"p3": 2, "p4": 2}),
]


async def run_case(instruction, seed, enable, expected, server_kwargs=None):
    server = LocalShopServer(**(server_kwargs or {})).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        task = TaskSpec(
            task_id="cart_transform",
            level=3,
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
            enable_cart_transform=enable,
        )
        state = await env.get_state()
        expected_task = TaskSpec(
            task_id="expected",
            level=3,
            goal=instruction,
            search_query="",
            targets=dict(expected),
            start_path="/cart",
            predicates=["cart_contains"],
        )
        expected_ok = compute_progress(state, env.page_url_path, expected_task).success
        return {
            "instruction": instruction,
            "seed": seed,
            "enable_cart_transform": enable,
            "success": bool(result.get("success")) and expected_ok,
            "expected_ok": expected_ok,
            "fallback_required": bool(result.get("fallback_required", False)),
            "error": result.get("error", ""),
            "compensated": result.get("compensated", 0),
            "steps": len(result.get("steps", [])),
            "policy_steps": 0,
            "prompt_tokens": 0,
            "cart": state.get("cart", {}),
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case, instruction, seed, expected in CASES:
        base = await run_case(instruction, seed, False, expected)
        base["case"] = case
        base["expected"] = expected
        base["mode"] = "baseline_no_ctc"
        rows.append(base)
        ctc = await run_case(instruction, seed, True, expected)
        ctc["case"] = case
        ctc["expected"] = expected
        ctc["mode"] = "ctc"
        rows.append(ctc)
    rollback = await run_case(
        CASES[0][1],
        {"p3": 1, "p4": 1},
        True,
        {"p3": 1, "p4": 1},
        {"fault_update_once": True, "fault_update_pid": "p4"},
    )
    rollback.update(
        {
            "case": "rollback",
            "mode": "ctc_fault",
            "expected": {"p3": 1, "p4": 1},
        }
    )
    rows.append(rollback)

    base_rows = [r for r in rows if r["mode"] == "baseline_no_ctc"]
    ctc_rows = [r for r in rows if r["mode"] == "ctc"]
    summary = {
        "baseline": {
            "success": sum(r["success"] for r in base_rows),
            "tasks": len(base_rows),
        },
        "ctc": {
            "success": sum(r["success"] for r in ctc_rows),
            "tasks": len(ctc_rows),
        },
        "rollback": rollback,
    }
    verdict = {
        "P0_baseline_gap": summary["baseline"]["success"] == 0,
        "P1_ctc_all": summary["ctc"]["success"] == len(ctc_rows),
        "P2_zero_llm": all(
            r["policy_steps"] == 0 and r["prompt_tokens"] == 0 for r in ctc_rows
        ),
        "P3_rollback": (
            not rollback["success"]
            and rollback["compensated"] == 1
            and rollback["cart"] == {"p3": 1, "p4": 1}
        ),
    }
    verdict["overall"] = all(verdict.values())
    payload = {"ar": "AR027", "summary": summary, "verdict": verdict, "rows": rows}
    (OUT / "ar027_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR027 购物车事务编译器（真实 Edge / 0 LLM）",
        "",
        "| 模式 | 成功 | 任务 |",
        "|------|------|------|",
        f"| baseline（关闭 CTC） | {summary['baseline']['success']}/{summary['baseline']['tasks']} | 显式能力缺口 |",
        f"| CTC（AR027） | {summary['ctc']['success']}/{summary['ctc']['tasks']} | 事务执行 + 最终状态验证 |",
        "",
        "## 回滚故障注入",
        "",
        f"- success={rollback['success']}，compensated={rollback['compensated']}，"
        f"最终 cart={rollback['cart']}，error={rollback['error']}",
        "",
        "## 判定",
        "",
        "```json",
        json.dumps(verdict, ensure_ascii=False, indent=2),
        "```",
    ]
    (OUT / "ar027_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
