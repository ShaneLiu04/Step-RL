"""AR012: CPU-first capability-gated runtime (no model loaded)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.capability import check_capability  # noqa: E402
from step_rl.edge.planner import fetch_catalog  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import PRODUCTS, LocalShopServer  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS, TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar012" / "eval"

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


def instruction_for(task):
    if task.level == 1:
        product = PRODUCTS[next(iter(task.targets))]
        return f"搜索{product.keywords[0]}"
    parts = [f"买{qty}件{PRODUCTS[pid].name}" for pid, qty in task.targets.items()]
    text = "，".join(parts)
    if task.require_checkout:
        text += "，并结算"
    return text


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


def build_cases():
    cases = []
    for task in EVAL_TASKS:
        cases.append((instruction_for(task), dict(task.targets), {}, "v1", False, task))
    for instruction, expected, stock in CONSTRAINT:
        cases.append(
            (
                instruction,
                expected,
                {"stock_overrides": stock} if stock else {},
                "v1",
                False,
                None,
            )
        )
    for instruction, expected, server_kwargs in DYNAMIC:
        cases.append((instruction, expected, server_kwargs, "v1", False, None))
    for instruction, expected in ERROR:
        cases.append(
            (
                instruction,
                expected,
                {
                    "checkout_name_requires_title": True,
                    "checkout_address_requires_road": True,
                },
                "v1",
                False,
                None,
            )
        )
    for task in EVAL_TASKS:
        cases.append((instruction_for(task), dict(task.targets), {}, "v2", True, task))
    return cases


async def run_one(case):
    instruction, expected, server_kwargs, layout, perturb, expected_task = case
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
        result = await run_task(env, instruction, None, None)
        state = await env.get_state()
        success = compute_progress(state, env.page_url_path, spec).success
        return {
            "instruction": instruction,
            "layout": layout,
            "perturb_ids": perturb,
            "success": success,
            "attempts": len(result["attempts"]),
            "fallback": result["fallback"],
            "fallback_required": result.get("fallback_required", False),
            "policy_steps": sum(1 for s in result["steps"] if s.source == "policy"),
            "skill_steps": sum(1 for s in result["steps"] if s.source == "skill"),
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
    OUT.mkdir(parents=True, exist_ok=True)
    torch.cuda.reset_peak_memory_stats()
    cases = build_cases()
    rows = []
    for case in cases:
        rows.append(await run_one(case))

    subset = cases[:12]
    serial_start = time.time()
    for case in subset:
        await run_one(case)
    serial_seconds = round(time.time() - serial_start, 2)

    sem = asyncio.Semaphore(4)

    async def guarded(case):
        async with sem:
            return await run_one(case)

    conc_start = time.time()
    conc = await asyncio.gather(*(guarded(case) for case in subset))
    concurrent_seconds = round(time.time() - conc_start, 2)

    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        catalog = fetch_catalog(server.base_url)
        cap = check_capability("帮我写一首诗", catalog)
        await env.start()
        unsupported = await run_task(env, "帮我写一首诗", None, None)
    finally:
        await env.close()
        server.stop()

    summary = {
        "tasks": len(rows),
        "success_rate": sum(r["success"] for r in rows) / max(1, len(rows)),
        "policy_steps": sum(r["policy_steps"] for r in rows),
        "skill_steps": sum(r["skill_steps"] for r in rows),
        "serial_12_seconds": serial_seconds,
        "concurrent4_12_seconds": concurrent_seconds,
        "concurrent_success_rate": sum(r["success"] for r in conc) / len(conc),
        "unsupported_covered": cap.covered,
        "unsupported_fallback_required": unsupported.get("fallback_required", False),
        "gpu_memory_bytes": (
            torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
        ),
        "model_loaded": False,
    }
    (OUT / "ar012_results.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# AR012 CPU-first 能力门控运行时",
        "",
        f"- 30 场景成功率：{summary['success_rate']:.1%}",
        f"- LLM 调用：{summary['policy_steps']}",
        f"- GPU 显存占用：{summary['gpu_memory_bytes']} bytes（未加载模型）",
        f"- 串行 12 任务：{serial_seconds}s",
        f"- 4 路并发 12 任务：{concurrent_seconds}s，成功 {summary['concurrent_success_rate']:.1%}",
        f"- 未覆盖指令：covered={cap.covered}, fallback_required={summary['unsupported_fallback_required']}",
        "",
        "## 逐场景",
        "",
        "| 指令 | 布局 | churn | 成功 | 尝试 | LLM 步 | 技能步 |",
        "|------|------|-------|------|------|--------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['instruction'][:32]} | {r['layout']} | "
            f"{'是' if r['perturb_ids'] else '否'} | "
            f"{'✓' if r['success'] else '✗'} | {r['attempts']} | "
            f"{r['policy_steps']} | {r['skill_steps']} |"
        )
    (OUT / "ar012_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
