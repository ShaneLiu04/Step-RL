"""AR020 pre-change baseline probe (run on the AR019 code state).

Evidence for the two defects that AR020 fixes, measured on the real
planner, the real persisted AR019 induced template and the real browser:

  A  planner: batch instruction loses the second product
  B  instantiation: batch TaskSpec through the old `_materialize`
     leaves the second product in the cart (verifier fails)
  C  control: single-product task on the same template succeeds
     (environment/template are sound; only the batch path is broken)

Outputs: outputs/ar020/baseline_probe.json + baseline_probe.md
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    load_induced_skills,
    run_skill_hierarchy,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar020"
AR019_TEMPLATE = ROOT / "outputs" / "ar019" / "eval" / "induced_skills.json"

BATCH_INSTRUCTION = "把无线充电器和蓝牙降噪耳机从购物车移除"


def batch_task() -> TaskSpec:
    return TaskSpec(
        task_id="probe_batch",
        level=2,
        goal=BATCH_INSTRUCTION,
        search_query="x",
        targets={"p3": 0, "p4": 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={"p3": 2, "p4": 3},
    )


def single_task() -> TaskSpec:
    return TaskSpec(
        task_id="probe_single",
        level=2,
        goal="把购物车中的无线充电器移除",
        search_query="x",
        targets={"p3": 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={"p3": 2},
    )


async def run_task(task: TaskSpec) -> dict:
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, task)
        return {
            "task_id": task.task_id,
            "targets": dict(task.targets),
            "success": progress.success,
            "cart": final.get("cart"),
            "steps": rollout.total_steps,
            "llm_calls": 0,
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
    results: dict = {"ar": "AR020", "note": "pre-change baseline probe", "probes": {}}

    # ---- A: planner on the batch instruction -----------------------------
    clear_induced_skills()
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
    finally:
        server.stop()
    spec = plan_instruction(BATCH_INSTRUCTION, catalog)
    results["probes"]["A_planner"] = {
        "instruction": BATCH_INSTRUCTION,
        "operation": spec.operation if spec else None,
        "targets": dict(spec.targets) if spec else None,
        "seed_cart": dict(spec.seed_cart) if spec else None,
        "second_product_kept": bool(
            spec and "p4" in spec.targets
        ),
    }
    print(json.dumps(results["probes"]["A_planner"], ensure_ascii=False), flush=True)

    # ---- B: batch task through the (old) materialisation ----------------
    loaded = load_induced_skills(str(AR019_TEMPLATE))
    print(json.dumps({"registered": loaded}, ensure_ascii=False), flush=True)
    probe_b = await run_task(batch_task())
    results["probes"]["B_batch_old_materialize"] = probe_b
    print(json.dumps(probe_b, ensure_ascii=False), flush=True)

    # ---- C: single-product control ---------------------------------------
    probe_c = await run_task(single_task())
    results["probes"]["C_single_control"] = probe_c
    print(json.dumps(probe_c, ensure_ascii=False), flush=True)

    (OUT / "baseline_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR020 改动前基线探针（AR019 代码状态）",
        "",
        f"- 指令：`{BATCH_INSTRUCTION}`",
        f"- A 规划：targets={results['probes']['A_planner']['targets']}，"
        f"第二商品保留={results['probes']['A_planner']['second_product_kept']}",
        f"- B 批量（旧实例化）：success={probe_b['success']}，"
        f"最终购物车={probe_b['cart']}，{probe_b['seconds']}s",
        f"- C 单商品对照：success={probe_c['success']}，"
        f"最终购物车={probe_c['cart']}，{probe_c['seconds']}s",
        "",
    ]
    (OUT / "baseline_probe.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"done": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
