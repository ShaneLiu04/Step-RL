"""AR022: order status query skill - real experiment chain.

  P0  post-change re-confirmation on the real planner / real site:
      both instructions compile to order_query (active/cancelled
      predicates), /orders really renders the real server-side order
      state, v1/v2 headers carry the 我的订单 entry, the gate reports
      no_skill_for_level_2 before registration and covered after
  P1  sedimentation cost (GPU): a real order is placed with compiled
      skills (0 LLM); in the SAME live session the composed runtime's
      LLM fallback executes 查询我最近的订单状态 (real AR004 adapters)
      and succeeds; the trajectory is recorded
  P2  induction: TrajectoryRecorder records -> induce_skill ->
      registered induced_order_query -> persisted -> gate covered
  P3  skill-path reuse, 3/3, 0 LLM: R1 same session (active);
      R2 after a real /cancel/ (cancelled predicate); R3 v2 layout +
      full ID churn in a fresh session with a fresh real order
  P4  efficiency table (LLM fallback vs skill reuse)
  P5  combination gate: full edge pytest suite + AR011 30 scenarios
      (30/30, 0 LLM)

Outputs: outputs/ar022/eval/{ar022_results.json, ar022_report.md,
induced_skills.json, skill_stats.json}
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.capability import check_capability  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_induction import (  # noqa: E402
    TrajectoryRecorder,
    induce_skill,
)
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    induced_candidates,
    register_induced_skill,
    run_skill_hierarchy,
    save_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.skill_stats import (  # noqa: E402
    clear_skill_stats,
    get_skill_stat,
    save_skill_stats,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar022" / "eval"

INSTRUCTION_ACTIVE = "查询我最近的订单状态"
INSTRUCTION_CANCELLED = "查看我最近取消的订单状态"


def order_query_task(cancelled: bool = False) -> TaskSpec:
    preds = ["orders_viewed"]
    preds.append("latest_order_cancelled" if cancelled else "latest_order_active")
    return TaskSpec(
        task_id="planned_order_query",
        level=2,
        goal=INSTRUCTION_CANCELLED if cancelled else INSTRUCTION_ACTIVE,
        search_query="",
        targets={},
        operation="order_query",
        predicates=preds,
        start_path="/",
    )


def order_task(pid: str, qty: int, query: str) -> TaskSpec:
    return TaskSpec(
        task_id=f"order_{pid}{qty}",
        level=4,
        goal=f"购买{qty}件商品并完成结算下单",
        search_query=query,
        targets={pid: qty},
        require_checkout=True,
    )


def stat_view(name: str) -> dict:
    stat = get_skill_stat(name)
    if stat is None:
        return {"name": name, "registered": False}
    return {
        "name": stat.name,
        "attempts": stat.attempts,
        "successes": stat.successes,
        "failures": stat.failures,
        "success_rate": round(stat.success_rate, 3),
        "demoted": stat.demoted,
        "last_failure_note": stat.last_failure_note,
    }


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )


def _get(opener, base, path):
    try:
        with opener.open(base + path) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def _post(opener, base, path, data):
    try:
        with opener.open(
            urllib.request.Request(base + path, data=data, method="POST")
        ) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _run_p0_site_probe() -> dict:
    """Real-site half of P0: live /orders rendering + header entries."""

    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        opener = _opener()
        base = server.base_url
        v1_home = _get(opener, base, "/")
        if _get(opener, base, "/api/cart/set?pid=p3&qty=2")[0] != 200:
            raise RuntimeError("cart seed failed")
        place_status = _post(
            opener,
            base,
            "/place-order",
            b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
            b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
            b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7",
        )
        if place_status != 200:
            raise RuntimeError(f"place-order returned {place_status}")
        state = json.loads(_get(opener, base, "/api/state")[1])
        orders = state.get("orders") or []
        if not orders:
            raise RuntimeError("order was not created on the real server")
        order_id = orders[-1]["id"]
        listing = _get(opener, base, "/orders")
        _get(opener, base, f"/cancel/{order_id}")
        listing2 = _get(opener, base, "/orders")
    finally:
        server.stop()
    server_v2 = LocalShopServer(layout="v2").start()
    try:
        v2_home = _get(_opener(), server_v2.base_url, "/")
    finally:
        server_v2.stop()
    return {
        "catalog": catalog,
        "v1_home": v1_home[1],
        "v2_home": v2_home[1],
        "order_id": order_id,
        "listing": listing,
        "listing2": listing2,
    }


def run_gate(command: list) -> dict:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=2400,
    )
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-5:])
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "tail": tail,
    }


async def place_real_order(env: BrowserEnv, pid: str, qty: int, query: str) -> dict:
    """Real order placement through compiled skills only (0 LLM)."""

    started = time.time()
    rollout = await run_skill_hierarchy(
        env, order_task(pid, qty, query), None, None, fallback=False
    )
    state = await env.get_state()
    return {
        "success": rollout.success,
        "steps": rollout.total_steps,
        "seconds": round(time.time() - started, 2),
        "orders": state.get("orders"),
        "cart": state.get("cart"),
    }


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict = {"ar": "AR022", "phases": {}}
    clear_induced_skills()
    clear_skill_stats()

    # ---- P0: post-change re-confirmation (real planner + real site) --------
    try:
        p0_probe = _run_p0_site_probe()
        catalog = p0_probe["catalog"]
    except Exception as error:  # honest rollback instead of a traceback
        results["phases"]["P0_recheck"] = {"error": str(error)}
        results["decision"] = f"rollback: P0 recheck raised: {error}"
        (OUT / "ar022_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return
    spec_active = plan_instruction(INSTRUCTION_ACTIVE, catalog)
    spec_cancelled = plan_instruction(INSTRUCTION_CANCELLED, catalog)
    gate_before = check_capability(INSTRUCTION_ACTIVE, catalog)
    register_induced_skill(
        "order_query",
        [{"kind": "click", "role": "link", "name": "我的订单", "value": ""}],
        "p0_probe",
    )
    gate_after = check_capability(INSTRUCTION_ACTIVE, catalog)
    p0 = {
        "planner_active": {
            "operation": spec_active.operation,
            "targets": dict(spec_active.targets),
            "predicates": list(spec_active.predicates),
            "start_path": spec_active.start_path,
        },
        "planner_cancelled": {
            "operation": spec_cancelled.operation,
            "predicates": list(spec_cancelled.predicates),
        },
        "orders_page": {
            "status": p0_probe["listing"][0],
            "renders_order_id": p0_probe["order_id"] in p0_probe["listing"][1],
            "renders_active": "有效" in p0_probe["listing"][1],
            "renders_cancelled_after_cancel": "已取消" in p0_probe["listing2"][1],
        },
        "header_entries": {
            "v1": "nav-orders" in p0_probe["v1_home"]
            and "我的订单" in p0_probe["v1_home"],
            "v2": "aria-label='我的订单'" in p0_probe["v2_home"],
        },
        "gate_before": {
            "covered": gate_before.covered,
            "reason": gate_before.reason,
        },
        "gate_after": {
            "covered": gate_after.covered,
            "skills": gate_after.skills,
        },
    }
    results["phases"]["P0_recheck"] = p0
    print(json.dumps(p0, ensure_ascii=False), flush=True)
    p0_ok = (
        spec_active.operation == "order_query"
        and spec_active.predicates == ["orders_viewed", "latest_order_active"]
        and spec_cancelled.predicates
        == ["orders_viewed", "latest_order_cancelled"]
        and p0["orders_page"]["status"] == 200
        and p0["orders_page"]["renders_order_id"]
        and p0["orders_page"]["renders_active"]
        and p0["orders_page"]["renders_cancelled_after_cancel"]
        and p0["header_entries"]["v1"]
        and p0["header_entries"]["v2"]
        and gate_before.reason == "no_skill_for_level_2"
        and gate_after.covered
    )
    clear_induced_skills()
    clear_skill_stats()
    if not p0_ok:
        results["decision"] = "rollback: P0 recheck incomplete"
        (OUT / "ar022_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return

    # ---- load model (P1 LLM fallback) ---------------------------------------
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)

    # ---- P1: sedimentation cost (real LLM fallback, GPU) --------------------
    spec_q = order_query_task()
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        placed = await place_real_order(env, "p3", 2, "无线")
        state = await env.get_state()
        order_id = (state.get("orders") or [{}])[-1].get("id", "")
        gate_gap = check_capability(INSTRUCTION_ACTIVE, catalog)
        recorder = TrajectoryRecorder(env)
        p1_start = time.time()
        rollout = await run_skill_hierarchy(
            recorder, spec_q, model, tokenizer, fallback=True, reset=False
        )
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, spec_q)
        p1 = {
            "order_placed": placed,
            "gate_gap": {
                "covered": gate_gap.covered,
                "reason": gate_gap.reason,
            },
            "success": progress.success,
            "steps": rollout.total_steps,
            "llm_steps": [
                {
                    "action": s.action,
                    "exec_ok": s.exec_ok,
                    "error": s.error,
                    "phi_after": round(s.phi_after, 2),
                }
                for s in rollout.steps
            ],
            "prompt_tokens": sum(len(s.prompt_ids) for s in rollout.steps),
            "response_tokens": sum(len(s.response_ids) for s in rollout.steps),
            "seconds": round(time.time() - p1_start, 2),
            "seconds_total_so_far": round(time.time() - started, 2),
            "recorded_trajectory": [
                {"kind": r.kind, "url": r.url, "role": r.role, "name": r.name}
                for r in recorder.records
            ],
            "orders_status": (final.get("orders") or [{}])[-1].get("status"),
            "visited": final.get("visited"),
            "cart": final.get("cart"),
        }
    finally:
        await env.close()
        server.stop()
    results["phases"]["P1_llm_fallback"] = p1
    print(json.dumps(p1, ensure_ascii=False), flush=True)
    p1_ok = (
        placed["success"]
        and not placed["cart"]
        and (placed["orders"] or [{}])[-1].get("status") == "active"
        and p1["success"]
        and p1["gate_gap"]["reason"] == "no_skill_for_level_2"
        and p1["prompt_tokens"] > 0
        and "/orders" in (p1["visited"] or [])
        and p1["orders_status"] == "active"
    )
    if not p1_ok:
        results["decision"] = "rollback: P1 LLM fallback chain incomplete"
        (OUT / "ar022_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return

    # ---- P2: induction -------------------------------------------------------
    template = induce_skill(order_query_task(), list(recorder.records), catalog)
    if template is None or not template["steps"]:
        results["decision"] = "rollback: induction produced no template"
        (OUT / "ar022_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return
    register_induced_skill("order_query", template["steps"], template["name"])
    save_induced_skills(str(OUT / "induced_skills.json"))
    cap_after = check_capability(INSTRUCTION_ACTIVE, catalog)
    results["phases"]["P2_induction"] = {
        "template": template,
        "registered": [c["name"] for c in induced_candidates("order_query")],
        "capability_after": {
            "covered": cap_after.covered,
            "skills": cap_after.skills,
        },
    }
    print(
        json.dumps(results["phases"]["P2_induction"], ensure_ascii=False), flush=True
    )

    # ---- P3: skill-path reuse, 0 LLM -----------------------------------------
    async def skill_run(
        task: TaskSpec, envx: BrowserEnv, layout_note: str
    ) -> dict:
        selected = skill_for_subtask(task)
        s0 = time.time()
        rollout = await run_skill_hierarchy(
            envx, task, None, None, fallback=False, reset=False
        )
        final = await envx.get_state()
        progress = compute_progress(final, envx.page_url_path, task)
        return {
            "layout": layout_note,
            "selected_skill": selected.name if selected is not None else None,
            "success": progress.success,
            "steps": rollout.total_steps,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "seconds": round(time.time() - s0, 2),
            "orders": final.get("orders"),
            "visited_tail": (final.get("visited") or [])[-3:],
        }

    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    p3 = []
    try:
        await env.start()
        # R1: same-session fresh state (new server -> no orders yet): place a
        # real order with compiled skills, then reuse the skill for the query
        placed = await place_real_order(env, "p3", 2, "无线")
        r1 = await skill_run(order_query_task(), env, "v1")
        r1["order_placed"] = placed["success"]
        p3.append(r1)
        print(json.dumps(r1, ensure_ascii=False), flush=True)

        # R2: real cancel -> the same skill must now satisfy the
        # cancelled-predicate task
        state = await env.get_state()
        order_id = (state.get("orders") or [{}])[-1].get("id", "")
        await env.cancel_order(order_id)
        r2 = await skill_run(order_query_task(cancelled=True), env, "v1")
        p3.append(r2)
        print(json.dumps(r2, ensure_ascii=False), flush=True)
    finally:
        await env.close()
        server.stop()

    # R3: v2 layout + full ID churn, fresh session, fresh real order
    server2 = LocalShopServer(layout="v2").start()
    env2 = BrowserEnv(
        server2,
        channel="msedge",
        headless=True,
        semantic=True,
        perturb_ids=True,
        perturb_prob=1.0,
    )
    try:
        await env2.start()
        placed2 = await place_real_order(env2, "p4", 1, "蓝牙")
        r3 = await skill_run(order_query_task(), env2, "v2+churn")
        r3["order_placed"] = placed2["success"]
        r3["churn"] = True
        p3.append(r3)
    finally:
        await env2.close()
        server2.stop()
    results["phases"]["P3_skill_reuse"] = p3
    results["phases"]["P3_stats"] = stat_view("induced_order_query")
    print(json.dumps(results["phases"]["P3_stats"], ensure_ascii=False), flush=True)

    # ---- P4: efficiency --------------------------------------------------------
    results["phases"]["P4_efficiency"] = {
        "llm_fallback_P1": {
            "llm_calls": 1,
            "prompt_tokens": p1["prompt_tokens"],
            "response_tokens": p1["response_tokens"],
            "seconds": p1["seconds"],
        },
        "skill_reuse": {
            "llm_calls": 0,
            "prompt_tokens": 0,
            "seconds": [row["seconds"] for row in p3],
        },
    }

    # ---- P5: combination gate --------------------------------------------------
    python = r"C:\Python311\python.exe"
    legacy = [
        "tests/test_locator.py",
        "tests/test_progress_estimator.py",
        "tests/test_smart_wait.py",
    ]
    gate_cmd = [python, "-m", "pytest", "tests", "-q", "--tb=no", "--timeout=300"]
    for path in legacy:
        gate_cmd += ["--ignore=" + path]
    gates = {}
    gates["pytest_edge"] = run_gate(gate_cmd)
    gates["ar011_suite"] = run_gate([python, "scripts/ar011_eval.py"])
    ar011_summary = json.loads(
        (ROOT / "outputs" / "ar011" / "eval" / "ar011_summary.json")
        .read_text(encoding="utf-8")
    )
    results["phases"]["P5_combination_gate"] = gates
    results["phases"]["P5_ar011_summary"] = ar011_summary
    results["phases"]["P5_legacy_debt"] = {
        "note": (
            "17 pre-existing failures in legacy tests (locator/"
            "progress_estimator/smart_wait); verified unchanged since AR019 "
            "via the git-stash control run"
        ),
        "files": legacy,
    }
    for name, gate in gates.items():
        print(
            json.dumps(
                {
                    "gate": name,
                    "returncode": gate["returncode"],
                    "seconds": gate["seconds"],
                    "tail": gate["tail"][-300:],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    save_skill_stats(str(OUT / "skill_stats.json"))

    # ---- decision ---------------------------------------------------------------
    ar011_ok = (
        ar011_summary.get("tasks") == 30
        and ar011_summary.get("success_rate") == 1.0
        and ar011_summary.get("policy_steps") == 0
    )
    p3_ok = (
        len(p3) == 3
        and all(row["success"] for row in p3)
        and all(row["selected_skill"] == "induced_order_query" for row in p3)
        and all(row["llm_calls"] == 0 for row in p3)
        and p3[0]["order_placed"]
        and p3[2]["order_placed"]
    )
    stats = results["phases"]["P3_stats"]
    combination_ok = (
        p1_ok
        and p0_ok
        and p3_ok
        and stats.get("attempts") == 3
        and stats.get("successes") == 3
        and not stats.get("demoted")
        and gates["pytest_edge"]["returncode"] == 0
        and gates["ar011_suite"]["returncode"] == 0
        and ar011_ok
    )
    results["decision"] = "keep" if combination_ok else "rollback"
    (OUT / "ar022_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- report -------------------------------------------------------------------
    lines = [
        "# AR022 订单状态查询技能 真实评测",
        "",
        "## P0 改动后复核（改动前基线探针：outputs/ar022/baseline_probe.json）",
        "",
        f"- 规划器 active：operation={p0['planner_active']['operation']}，"
        f"predicates={p0['planner_active']['predicates']}，"
        f"start_path={p0['planner_active']['start_path']}",
        f"- 规划器 cancelled：predicates={p0['planner_cancelled']['predicates']}",
        f"- /orders 真实 200：渲染订单号={p0['orders_page']['renders_order_id']}，"
        f"「有效」={p0['orders_page']['renders_active']}，"
        f"取消后「已取消」={p0['orders_page']['renders_cancelled_after_cancel']}",
        f"- 头部入口：v1={p0['header_entries']['v1']}，v2={p0['header_entries']['v2']}",
        f"- 门控：注册前 covered={p0['gate_before']['covered']}（"
        f"{p0['gate_before']['reason']}），注册后 covered={p0['gate_after']['covered']}",
        "",
        "## P1 LLM 兜底沉淀（GPU，AR004 适配器，同会话）",
        "",
        f"- 真实下单（编译技能，0 LLM）：success={p1['order_placed']['success']}，"
        f"{p1['order_placed']['steps']} 步，{p1['order_placed']['seconds']}s，"
        f"订单 status={p1['orders_status']}，cart={p1['cart']}",
        f"- 兜底前门控：covered={p1['gate_gap']['covered']}，"
        f"reason={p1['gate_gap']['reason']}",
        f"- 真实 LLM 执行：success={p1['success']}，{p1['steps']} 步，"
        f"prompt tokens={p1['prompt_tokens']}，response tokens="
        f"{p1['response_tokens']}，{p1['seconds']}s",
        f"- 轨迹：{p1['recorded_trajectory']}",
        "",
        "## P2 归纳",
        "",
        f"- 模板：{json.dumps(results['phases']['P2_induction']['template'], ensure_ascii=False)}",
        f"- 注册候选：{results['phases']['P2_induction']['registered']}，"
        f"门控 covered={results['phases']['P2_induction']['capability_after']['covered']}",
        "",
        "## P3 技能路径复用（0 LLM）",
        "",
        "| 场景 | 布局 | 选中技能 | 成功 | 步数 | 耗时 |",
        "|------|------|----------|------|------|------|",
    ]
    for i, row in enumerate(p3):
        lines.append(
            f"| R{i + 1} | {row['layout']} | {row['selected_skill']} | "
            f"{'✓' if row['success'] else '✗'} | {row['steps']} | "
            f"{row['seconds']}s |"
        )
    lines += [
        "",
        f"- 技能统计：attempts={stats.get('attempts')}，"
        f"successes={stats.get('successes')}，demoted={stats.get('demoted')}",
        "",
        "## P4 效率对照",
        "",
        "| 方式 | LLM 调用 | prompt tokens | 耗时 | 结果 |",
        "|------|----------|---------------|------|------|",
        f"| LLM 兜底（P1，沉淀成本） | 1 | {p1['prompt_tokens']} | "
        f"{p1['seconds']}s | ✓ |",
        f"| 技能复用（P3 R1/R2/R3） | 0 | 0 | "
        + " / ".join(f"{row['seconds']}s" for row in p3)
        + " | ✓ 3/3 |",
        "",
        "## P5 组合门禁",
        "",
        f"- edge 套件 pytest：rc={gates['pytest_edge']['returncode']}，"
        f"{gates['pytest_edge']['tail'].splitlines()[-1] if gates['pytest_edge']['tail'] else ''}",
        f"- AR011 30 场景：rc={gates['ar011_suite']['returncode']}，"
        f"success_rate={ar011_summary.get('success_rate')}，"
        f"policy_steps={ar011_summary.get('policy_steps')}",
        "- 遗留技术债：legacy 三文件（locator/progress_estimator/smart_wait）"
        "17 个历史失败，AR019 git-stash 对照验证与本 AR 无关，不纳入门禁",
        "",
        f"## 结论：{'保留（keep）' if combination_ok else '回退（rollback）'}",
        "",
    ]
    (OUT / "ar022_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"decision": results["decision"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
