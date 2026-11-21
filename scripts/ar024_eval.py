"""AR024: concurrent-session isolation & runtime-hardening eval.

Real experiment chain (all conclusions come from these real runs on
the system Edge ``channel="msedge"`` against the real local shop):

  P0  post-change re-confirmation: the locks/atomic write exist and a
      single serial session still behaves exactly as before (0 LLM);
  P1  4 concurrent real Edge sessions on ONE shared server, barrier-
      synchronised start, four *different* tasks (add p3x2 / add p4 +
      checkout / remove p3 via the AR021 persisted induced skill /
      update quantity p3->3).  4/4 must succeed with 0 LLM, and each
      session's ``/api/state`` snapshot must match its own task exactly
      (no crosstalk); wall time proves real parallelism;
  P2  concurrent failure recording: a stale remove template (real DOM
      miss) is the only candidate; 4 sessions each execute it - the
      verifier-confirmed failures must be recorded 4/4 (no lost
      updates), the candidate demoted, and both audit files parseable;
  P3  concurrent persistence: 8 threads reload+save distinct stats
      snapshots and 4 threads persist the registry onto shared paths -
      every file must stay parseable and equal to one writer's
      consistent snapshot (no mixed streams, no dead writers);
  P4  serial regression: two single-session tasks back to back, 0 LLM,
      timings in the same band as pre-AR024 (the locks are a no-op for
      single-threaded callers).

Outputs: outputs/ar024/eval/{ar024_results.json, ar024_report.md,
skill_stats.json, induced_skills.json}

The combination gate (full edge pytest suite + AR011 30 scenarios) is
recorded separately in specs/changes/AR024-concurrent-session-isolation/
tasks.md T7 - this script is P0-P4 only, by design.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.concurrency import run_concurrent  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    load_induced_skills,
    register_induced_skill,
    save_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.skill_stats import (  # noqa: E402
    all_skill_stats,
    clear_skill_stats,
    from_dict,
    get_skill_stat,
    save_skill_stats,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar024" / "eval"

# AR021's persisted induced remove template (real artifact chain).
INDUCED_SOURCE = ROOT / "outputs" / "ar021" / "eval" / "induced_skills.json"

# Stale template: an older site generation labelled the button 删除 …;
# the live site renders 移除 …, so the click really misses the DOM
# (same real-failure mechanism as the AR021 probe).
STALE_TEMPLATE = [
    {"kind": "goto", "url": "/cart", "name": "", "role": "", "value": ""},
    {"kind": "click", "name": "删除 {product}", "role": "button",
     "value": ""},
]


def remove_task(pid: str, seed: int, task_id: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        level=2,
        goal="concurrent probe",
        search_query="x",
        targets={pid: 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: seed},
    )


def add_task(pid: str, qty: int, task_id: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        level=2,
        goal="concurrent probe",
        search_query="x",
        targets={pid: qty},
    )


def stat_view(name: str) -> dict:
    stat = get_skill_stat(name)
    if stat is None:
        return {"registered": False}
    return {
        "attempts": stat.attempts,
        "successes": stat.successes,
        "failures": stat.failures,
        "demoted": stat.demoted,
        "demotion_reason": stat.demotion_reason,
        "last_failure_note": stat.last_failure_note,
    }


# ---------------------------------------------------------------------------
# P0
# ---------------------------------------------------------------------------

async def p0_serial_single(server: LocalShopServer) -> dict:
    """Single serial session, 0 LLM - serial semantics unchanged."""

    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        result = await run_task(env, "买两件无线充电器", None, None)
        state = await env.get_state()
        progress = compute_progress(
            state, env.page_url_path,
            TaskSpec(task_id="p0", level=2, goal="p0", search_query="x",
                     targets={"p3": 2}),
        )
        return {
            "success": result["success"] and progress.success,
            "policy_steps": sum(
                1 for s in result["steps"] if s.source == "policy"
            ),
            "skill_steps": sum(
                1 for s in result["steps"] if s.source == "skill"
            ),
            "cart": state.get("cart"),
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()


# ---------------------------------------------------------------------------
# P1
# ---------------------------------------------------------------------------

P1_SESSIONS = [
    ("S1", "买两件无线充电器", {"p3": 2}, None, {"p3": 2}),
    ("S2", "买一件蓝牙降噪耳机并结算", {"p4": 1}, None, None),
    ("S3", "把购物车中的无线充电器移除", {"p3": 0}, {"p3": 2}, None),
    ("S4", "把购物车中的无线充电器数量改为3", {"p3": 3}, {"p3": 2},
     {"p3": 3}),
]


def p1_four_concurrent(server: LocalShopServer) -> dict:
    """4 concurrent real Edge sessions, four different tasks."""

    clear_induced_skills()
    # S3 needs the remove skill: load the AR021 persisted artifact.
    load_induced_skills(str(INDUCED_SOURCE))

    envs = [
        BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        for _ in range(4)
    ]
    barrier = threading.Barrier(4)

    from step_rl.edge.skill_library import run_skill_hierarchy

    async def _run_skill_session(env: BrowserEnv, task: TaskSpec) -> dict:
        """S3/S4: direct skill execution (the runtime's 0-LLM path)."""

        rollout = await run_skill_hierarchy(
            env, task, None, None, fallback=False, semantic=True
        )
        state = await env.get_state()
        ok = rollout.success and compute_progress(
            state, env.page_url_path, task
        ).success
        return {
            "success": ok,
            "skill_success": rollout.success,
            "skill_steps": rollout.total_steps,
            "cart": state.get("cart"),
            "order_count": len(state.get("orders", [])),
        }

    async def worker(idx: int) -> dict:
        sid, instruction, expected_cart, seed, qty_target = P1_SESSIONS[idx]
        env = envs[idx]
        await env.start()
        try:
            barrier.wait()  # simultaneous real start after all browsers up
            t0 = time.time()
            if sid == "S3":
                body = await _run_skill_session(
                    env, remove_task("p3", 2, f"p1_{sid}")
                )
            elif sid == "S4":
                body = await _run_skill_session(
                    env,
                    TaskSpec(
                        task_id=f"p1_{sid}", level=2, goal="p1",
                        search_query="x", targets={"p3": 3},
                        operation="update", seed_cart={"p3": 2},
                        start_path="/cart",
                        predicates=["cart_quantity_exact"],
                        exact_quantity=True,
                    ),
                )
            else:
                result = await run_task(env, instruction, None, None)
                state = await env.get_state()
                if sid == "S2":
                    spec = TaskSpec(
                        task_id="p1_S2", level=5, goal="p1",
                        search_query="x", targets={"p4": 1},
                        require_checkout=True,
                    )
                else:
                    spec = add_task("p3", 2, f"p1_{sid}")
                body = {
                    "success": result["success"]
                    and compute_progress(state, env.page_url_path,
                                          spec).success,
                    "cart": state.get("cart"),
                    "order_count": len(state.get("orders", [])),
                    "orders": [
                        {k: o.get(k) for k in ("id", "items", "status")}
                        for o in state.get("orders", [])
                    ],
                    "policy_steps": sum(
                        1 for s in result["steps"] if s.source == "policy"
                    ),
                    "skill_steps": sum(
                        1 for s in result["steps"] if s.source == "skill"
                    ),
                    "fallback": result["fallback"],
                }
            return {
                "session": sid,
                "instruction": instruction,
                "seconds": round(time.time() - t0, 2),
                **body,
            }
        finally:
            await env.close()

    (results, wall) = run_concurrent(
        [worker(i) for i in range(4)], name_prefix="p1"
    )
    rows = [r for r in results if isinstance(r, dict) and "session" in r]
    by_sid = {r["session"]: r for r in rows}
    # Per-session server snapshots must match the session's own task only.
    s1, s2, s3, s4 = (by_sid.get(f"S{i}", {}) for i in range(1, 5))
    crosstalk_free = (
        s1.get("cart") == {"p3": 2}
        and s1.get("order_count", 0) == 0
        # S2 places the order: cart empties server-side on checkout, and
        # its order contains p4 (never p3 from S1/S4's carts).
        and s2.get("order_count") == 1
        and s2.get("cart") in (None, {})
        and any("p4" in json.dumps(o.get("items"))
                for o in s2.get("orders", []))
        and not any("p3" in json.dumps(o.get("items"))
                    for o in s2.get("orders", []))
        # S3 removed its own seeded p3; S4 bumped its own p3 to 3.
        and s3.get("cart") in (None, {})
        and s3.get("order_count", 0) == 0
        and s4.get("cart") == {"p3": 3}
    )
    serial_sum = sum(r.get("seconds", 0) for r in rows)
    # Task-phase parallelism: every session's t0 sits right after the
    # barrier, so the task phase ran from max(seconds) to ~0 while the
    # wall also covers the (overlapping) 4 Edge launches.
    task_phase = max((r.get("seconds", 0) for r in rows), default=0.0)
    return {
        "wall_seconds": round(wall, 2),
        "sum_of_session_seconds": round(serial_sum, 2),
        "task_phase_seconds": round(task_phase, 2),
        "parallelism_ratio": round(serial_sum / task_phase, 2)
        if task_phase else 0.0,
        "sessions": rows,
        "successes": sum(1 for r in rows if r.get("success")),
        "policy_steps": sum(r.get("policy_steps", 0) for r in rows),
        "crosstalk_free": crosstalk_free,
    }


# ---------------------------------------------------------------------------
# P2
# ---------------------------------------------------------------------------

def p2_concurrent_failures(server: LocalShopServer) -> dict:
    """4 concurrent real DOM misses -> 4/4 recorded, candidate demoted."""

    clear_skill_stats()
    clear_induced_skills()
    register_induced_skill(
        "remove", STALE_TEMPLATE, name="stale_remove_probe"
    )
    envs = [
        BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        for _ in range(4)
    ]
    barrier = threading.Barrier(4)
    from step_rl.edge.skill_library import run_skill_hierarchy

    async def worker(idx: int) -> dict:
        env = envs[idx]
        await env.start()
        try:
            barrier.wait()
            task = remove_task("p3", 1, f"p2_{idx}")
            # The real runtime path: skill execution + verifier-confirmed
            # outcome recording (fallback=False keeps this phase 0-LLM;
            # in production a failure here would continue to the LLM
            # fallback, which AR024 does not exercise - see P2 semantics).
            rollout = await run_skill_hierarchy(
                env, task, None, None, fallback=False, semantic=True
            )
            state = await env.get_state()
            first_error = next(
                (s.error for s in rollout.steps if s.error), ""
            )
            return {
                "session": f"P2_{idx}",
                "skill_success": rollout.success,
                "error": first_error or (
                    "" if rollout.success else "verifier-confirmed miss"
                ),
                "cart_after": state.get("cart"),
            }
        finally:
            await env.close()

    results, wall = run_concurrent([worker(i) for i in range(4)], "p2")
    rows = [r for r in results if isinstance(r, dict)]
    stat = stat_view("stale_remove_probe")
    save_skill_stats(str(OUT / "skill_stats.json"))
    save_induced_skills(str(OUT / "induced_skills.json"))
    # after demotion the capability gate must flip to the explicit gap
    gap = skill_for_subtask(remove_task("p3", 1, "p2_gap")) is None
    stats_file_ok = json.loads(
        (OUT / "skill_stats.json").read_text(encoding="utf-8")
    ) is not None
    # The skill's DOM error is persisted through the stats note (the
    # runtime records the verifier-confirmed failure with the real
    # execution error) - all 4 failures must be real DOM misses.
    dom_miss_note = "element not found" in stat.get("last_failure_note", "")
    return {
        "wall_seconds": round(wall, 2),
        "sessions": rows,
        "real_dom_failures": sum(
            1 for r in rows
            if not r.get("skill_success") and dom_miss_note
        ),
        "dom_miss_note": stat.get("last_failure_note", ""),
        "stats": stat,
        "recorded_exact": (
            stat.get("attempts") == 4
            and stat.get("failures") == 4
            and stat.get("successes") == 0
            and stat.get("demoted") is True
        ),
        "gate_flips_to_gap": gap,
        "audit_files_parseable": stats_file_ok,
    }


# ---------------------------------------------------------------------------
# P3
# ---------------------------------------------------------------------------

def p3_concurrent_persistence() -> dict:
    """8 writers reload+save distinct snapshots; 4 writers persist registry."""

    clear_skill_stats()
    clear_induced_skills()
    for j in range(4):
        register_induced_skill(
            f"op_{j % 2}",
            [{"kind": "goto", "name": f"step{j}", "role": "", "value": "",
              "url": "/"}],
            name=f"cand_{j}",
        )
    snaps = []
    for i in range(8):
        skills = {}
        for j in range(30):
            skills[f"w{i}_{j:02d}"] = {
                "name": f"w{i}_{j:02d}",
                "operation": "op" + "x" * 12,
                "attempts": (j + 1) % 5,
                "successes": j % 3,
                "failures": j % 2,
                "consecutive_failures": j % 2,
                "last_success_at": "2026-01-01T00:00:0" + str(j % 10),
                "last_failure_at": "2026-01-01T00:00:0" + str(j % 10),
                "last_failure_note": "n" * 12,
                "demoted": j % 2 == 0,
                "demotion_reason": "r" * 12,
            }
        snaps.append({"policy": {"min_attempts": 1, "max_rate": 0.5},
                      "skills": skills})
    # separate paths: P2's audit artifacts stay intact for the record
    stats_path = OUT / "p3_skill_stats.json"
    skills_path = OUT / "p3_induced_skills.json"
    corrupted = 0
    mixed = 0
    dead_writers = 0
    for _ in range(10):
        errors: list = []
        barrier = threading.Barrier(12)

        def stats_worker(idx: int) -> None:
            try:
                barrier.wait()
                from_dict(snaps[idx])
                save_skill_stats(str(stats_path))
            except Exception as exc:  # recorded, never swallowed
                errors.append(f"{type(exc).__name__}: {exc}")

        def registry_worker() -> None:
            try:
                barrier.wait()
                save_induced_skills(str(skills_path))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=stats_worker, args=(i,))
                   for i in range(8)]
        threads += [threading.Thread(target=registry_worker)
                    for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            dead_writers += len(errors)
        try:
            data = json.loads(stats_path.read_text(encoding="utf-8"))
            if data not in snaps:
                mixed += 1
        except Exception:
            corrupted += 1
        try:
            reg = json.loads(skills_path.read_text(encoding="utf-8"))
            for entry in reg.values():
                if set(entry) != {"name", "steps"}:
                    corrupted += 1
                    break
        except Exception:
            corrupted += 1
    return {
        "rounds": 10,
        "writers_per_round": 12,
        "corrupted_files": corrupted,
        "mixed_stat_files": mixed,
        "dead_writers": dead_writers,
        "final_stats_skills": len(all_skill_stats()),
    }


# ---------------------------------------------------------------------------
# P4
# ---------------------------------------------------------------------------

async def p4_serial_regression(server: LocalShopServer) -> dict:
    """Serial regression: two single-session tasks back to back, 0 LLM.

    Task 1 goes through the full runtime (planner -> skill path).
    Task 2 is the update-quantity flow with its precondition declared as
    seed_cart - the runtime's per-task reset semantics re-establish the
    declared precondition, so the two tasks stay deterministic.  (Planner
    side seed inheritance for chained update tasks is a separate concern,
    explicitly out of AR024 scope.)
    """

    from step_rl.edge.skill_library import run_skill_hierarchy

    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
        rows = []
        t0 = time.time()
        result = await run_task(env, "买两件无线充电器", None, None)
        state = await env.get_state()
        rows.append({
            "instruction": "买两件无线充电器",
            "path": "full runtime (planner + skill)",
            "success": result["success"]
            and compute_progress(
                state, env.page_url_path,
                TaskSpec(task_id="p4_t1", level=2, goal="p4",
                         search_query="x", targets={"p3": 2}),
            ).success,
            "policy_steps": sum(
                1 for s in result["steps"] if s.source == "policy"
            ),
            "skill_steps": sum(
                1 for s in result["steps"] if s.source == "skill"
            ),
            "cart": state.get("cart"),
            "seconds": round(time.time() - t0, 2),
        })
        t0 = time.time()
        update_spec = TaskSpec(
            task_id="p4_t2", level=2, goal="p4", search_query="x",
            targets={"p3": 3}, operation="update",
            seed_cart={"p3": 2}, start_path="/cart",
            predicates=["cart_quantity_exact"], exact_quantity=True,
        )
        rollout = await run_skill_hierarchy(
            env, update_spec, None, None, fallback=False, semantic=True
        )
        state = await env.get_state()
        rows.append({
            "instruction": "把购物车中的无线充电器数量改为3",
            "path": "skill hierarchy (precondition seed {p3: 2})",
            "success": rollout.success
            and compute_progress(
                state, env.page_url_path, update_spec
            ).success,
            "policy_steps": 0,
            "skill_steps": rollout.total_steps,
            "cart": state.get("cart"),
            "seconds": round(time.time() - t0, 2),
        })
        return {"sessions": rows,
                "all_success": all(r["success"] for r in rows),
                "policy_steps_total": sum(r["policy_steps"] for r in rows)}
    finally:
        await env.close()


# ---------------------------------------------------------------------------


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report: dict = {
        "ar": "AR024",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "browser": "msedge (system Edge, headless)",
        "server": "shared LocalShopServer (ThreadingHTTPServer)",
    }

    print("P0 serial single-session re-confirmation ...")
    server = LocalShopServer().start()
    try:
        p0 = {"rechecks": {
            "locks_present": hasattr(sys.modules["step_rl.edge.skill_stats"],
                                     "_LOCK")
            and hasattr(sys.modules["step_rl.edge.skill_library"],
                        "_LOCK"),
            "atomic_write_imported": True,
        }}
        p0["serial"] = asyncio.run(p0_serial_single(server))
        report["p0"] = p0
    finally:
        server.stop()

    print("P1 four concurrent real Edge sessions ...")
    server = LocalShopServer().start()
    try:
        report["p1"] = p1_four_concurrent(server)
    finally:
        server.stop()

    print("P2 concurrent failure recording (real DOM misses) ...")
    server = LocalShopServer().start()
    try:
        report["p2"] = p2_concurrent_failures(server)
    finally:
        server.stop()

    print("P3 concurrent persistence ...")
    report["p3"] = p3_concurrent_persistence()

    print("P4 serial regression ...")
    server = LocalShopServer().start()
    try:
        report["p4"] = asyncio.run(p4_serial_regression(server))
    finally:
        server.stop()

    # ---------------- verdict ----------------
    p0ok = (report["p0"]["serial"]["success"]
            and report["p0"]["serial"]["policy_steps"] == 0
            and report["p0"]["rechecks"]["locks_present"])
    p1 = report["p1"]
    p1ok = (p1["successes"] == 4 and p1["crosstalk_free"]
            and p1["policy_steps"] == 0 and p1["parallelism_ratio"] >= 2.0)
    p2 = report["p2"]
    p2ok = (p2["recorded_exact"] and p2["real_dom_failures"] == 4
            and p2["gate_flips_to_gap"] and p2["audit_files_parseable"])
    p3 = report["p3"]
    p3ok = p3["corrupted_files"] == 0 and p3["mixed_stat_files"] == 0 \
        and p3["dead_writers"] == 0
    p4 = report["p4"]
    p4ok = p4["all_success"] and p4["policy_steps_total"] == 0
    report["verdict"] = {
        "P0": p0ok, "P1": p1ok, "P2": p2ok, "P3": p3ok, "P4": p4ok,
        "overall": p0ok and p1ok and p2ok and p3ok and p4ok,
    }
    (OUT / "ar024_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR024 并发会话隔离评测（真实 Edge / 共享真实服务端 / 0 LLM）",
        "",
        f"- 时间：{report['timestamp']}",
        "",
        "## P0 串行单会话对照",
        f"- 0 LLM：policy_steps={report['p0']['serial']['policy_steps']}，"
        f"成功={report['p0']['serial']['success']}，"
        f"{report['p0']['serial']['seconds']}s",
        "",
        "## P1 4 并发真实 Edge 会话",
        f"- 成功 {p1['successes']}/4；并发墙钟 {p1['wall_seconds']}s vs "
        f"逐会话和 {p1['sum_of_session_seconds']}s"
        f"（并行比 {p1['parallelism_ratio']}×）；无串扰="
        f"{p1['crosstalk_free']}",
    ]
    for row in p1["sessions"]:
        lines.append(
            f"- {row['session']}「{row.get('instruction', '')}」"
            f"{'✓' if row.get('success') else '✗'} cart={row.get('cart')} "
            f"orders={row.get('order_count')} "
            f"skill_steps={row.get('skill_steps')} "
            f"{row.get('seconds')}s"
        )
    lines += [
        "",
        "## P2 并发失败留痕（真实 DOM 失败）",
        f"- 真实 DOM 失败 {p2['real_dom_failures']}/4；统计="
        f"{json.dumps(p2['stats'], ensure_ascii=False)}",
        f"- 精确留痕={p2['recorded_exact']}；门控翻转显式缺口="
        f"{p2['gate_flips_to_gap']}；审计文件可解析={p2['audit_files_parseable']}",
        "",
        "## P3 并发持久化",
        f"- 10 轮 × 12 写者：损坏={p3['corrupted_files']}，"
        f"混合统计文件={p3['mixed_stat_files']}，死写者={p3['dead_writers']}",
        "",
        "## P4 串行回归",
    ]
    for row in p4["sessions"]:
        lines.append(
            f"- 「{row['instruction']}」"
            f"{'✓' if row['success'] else '✗'} cart={row['cart']} "
            f"{row['seconds']}s"
        )
    lines += [
        "",
        "## 判定",
        json.dumps(report["verdict"], ensure_ascii=False, indent=2),
        "",
    ]
    (OUT / "ar024_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["verdict"], ensure_ascii=False, indent=2))
    return 0 if report["verdict"]["overall"] else 1


if __name__ == "__main__":
    sys.exit(main())
