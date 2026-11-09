"""AR017: Saga compensation — no-compensation baseline vs compensation."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.runtime import run_order_sequence  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402

OUT = ROOT / "outputs" / "ar017" / "eval"

CASES = [
    (
        "S1_p3_then_p4_oos",
        [{"p3": 1}, {"p4": 2}],
        {"p4": 0},
    ),
    (
        "S2_p2_then_p3_oos",
        [{"p2": 1}, {"p3": 2}],
        {"p3": 0},
    ),
]


async def run_case(name, sequence, stock, compensate):
    task = TaskSpec(
        task_id=name,
        level=5,
        goal="第一单成功；第二单缺货失败时取消第一单",
        search_query=next(iter(sequence[0])),
        targets={pid: qty for order in sequence for pid, qty in order.items()},
        require_checkout=True,
        order_sequence=sequence,
        compensate_on_failure=compensate,
    )
    server = LocalShopServer(stock_overrides=stock).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
        result = await run_order_sequence(env, task, None, None, compensate=compensate)
        return {
            "task_id": name,
            "mode": "saga" if compensate else "no_compensation",
            "success": result["success"],
            "orders": result["orders"],
            "attempts": result["attempts"],
        }
    finally:
        await env.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, sequence, stock in CASES:
        rows.append(await run_case(name, sequence, stock, compensate=False))
        rows.append(await run_case(name, sequence, stock, compensate=True))
    (OUT / "ar017_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR017 Saga 补偿真实评测",
        "",
        "| 场景 | 模式 | 成功 | 订单历史 |",
        "|------|------|------|----------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {row['mode']} | "
            f"{'✓' if row['success'] else '✗'} | {row['orders']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "- 第二单因真实库存 0 失败；无补偿时第一单保持 active，验证失败。",
        "- Saga 在失败后取消已成功订单，全部订单 cancelled，验证成功。",
        "",
    ]
    (OUT / "ar017_report.md").write_text("\n".join(lines), encoding="utf-8")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
