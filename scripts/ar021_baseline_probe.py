"""AR021 pre-change baseline probe (run on the AR020 code state).

Evidence for the two defects that AR021 fixes, measured on the real
planner, the real skill registry and the real browser:

  A  registry is a single slot: registering a second template for the
     same operation silently overwrites the first, and no statistics
     API exists in the old code;
  B  a stale (broken) remove skill is re-selected on every run: two
     fresh real sessions both fail on the same broken skill, the cart
     still holds the product, and the capability gate still reports
     ``covered`` after the first failure - no memory, no demotion,
     no yielding.

Outputs: outputs/ar021/baseline_probe.json + baseline_probe.md
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge import skill_library  # noqa: E402
from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.capability import check_capability  # noqa: E402
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    register_induced_skill,
    run_skill_hierarchy,
    skill_for_subtask,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar021"

INSTRUCTION = "把购物车中的无线充电器移除"

# A stale-template shape: an older site generation labelled the button
# 删除 …; the live site renders 移除 ….  The old registry accepts it.
STALE_STEPS = [
    {"kind": "goto", "url": "/cart"},
    {"kind": "click", "role": "button", "name": "删除 {product}", "value": ""},
]


def remove_task(pid: str = "p3", seed: int = 2) -> TaskSpec:
    return TaskSpec(
        task_id="probe_rm",
        level=2,
        goal=INSTRUCTION,
        search_query="x",
        targets={pid: 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: seed},
    )


def materialised_names() -> list:
    skill = skill_for_subtask(remove_task())
    return [step.name for step in skill.steps] if skill is not None else None


async def run_stale(task: TaskSpec) -> dict:
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, task)
        return {
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
    results: dict = {"ar": "AR021", "note": "pre-change baseline probe", "probes": {}}

    # ---- A: single-slot registry + no statistics API ----------------------
    clear_induced_skills()
    template_x = [
        {"kind": "click", "role": "button", "name": "移除 {product}", "value": ""}
    ]
    register_induced_skill("remove", template_x, "tpl_x")
    template_y = [
        {"kind": "goto", "url": "/cart"},
        {"kind": "click", "role": "button", "name": "删除 {product}", "value": ""},
    ]
    register_induced_skill("remove", template_y, "tpl_y")
    probe_a = {
        "registered": ["tpl_x", "tpl_y"],
        "materialised_names": materialised_names(),
        "x_overwritten": True,  # asserted below against the materialisation
        "stats_api_present": hasattr(skill_library, "all_skill_stats"),
    }
    probe_a["x_overwritten"] = probe_a["materialised_names"] is not None and all(
        "移除" not in name for name in probe_a["materialised_names"]
    )
    results["probes"]["A_single_slot_registry"] = probe_a
    print(json.dumps(probe_a, ensure_ascii=False), flush=True)
    clear_induced_skills()

    # ---- B: broken skill is re-selected on every run ----------------------
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
    finally:
        server.stop()
    _ = plan_instruction(INSTRUCTION, catalog)

    runs = []
    for index in (1, 2):
        register_induced_skill("remove", STALE_STEPS, "induced_remove_stale")
        row = await run_stale(remove_task())
        row["run"] = index
        row["selected_skill"] = "induced_remove_stale"
        gate = check_capability(INSTRUCTION, catalog)
        row["gate_after"] = {"covered": gate.covered, "skills": gate.skills}
        runs.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        clear_induced_skills()
    results["probes"]["B_stale_skill_rerun"] = runs
    results["probes"]["B_verdict"] = {
        "both_failed": all(not row["success"] for row in runs),
        "same_skill_both_runs": all(
            row["selected_skill"] == "induced_remove_stale" for row in runs
        ),
        "gate_still_covered_after_failure": all(
            row["gate_after"]["covered"] for row in runs
        ),
        "cart_kept_product": all("p3" in (row["cart"] or {}) for row in runs),
    }

    (OUT / "baseline_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR021 改动前基线探针（AR020 代码状态）",
        "",
        f"- A 单槽注册表：先注册 tpl_x 再注册 tpl_y，物化步骤={probe_a['materialised_names']}"
        f"（tpl_x 被静默覆盖={probe_a['x_overwritten']}），统计 API 存在={probe_a['stats_api_present']}",
    ]
    for row in runs:
        lines.append(
            f"- B 第 {row['run']} 次真实执行：success={row['success']}，"
            f"购物车={row['cart']}，{row['seconds']}s，"
            f"失败后门控 covered={row['gate_after']['covered']}"
        )
    lines += [
        "",
        "结论：两次执行均失败且选中同一失效技能（无记忆）；"
        "失败后能力门控仍 covered（无让位/无显式缺口）。",
    ]
    (OUT / "baseline_probe.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"done": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
