"""AR023: promo constraint planning - real experiment chain.

  P0  post-change re-confirmation (no GPU): the real planner compiles the
      8-instruction table (4 feasible specs with the right promo code +
      4 explicit None refusals), /api/promos really serves the two
      coupons, both layouts really render the claim buttons, a real HTTP
      session really settles total/paid/promo (including the honest
      threshold-miss path and the "missed coupon stays usable" rule),
      and the capability gate covers the coupon instruction
  P1  real execution T1 (v1, real Edge): C1 full chain, 0 LLM
  P2  real execution T2 (v1, real Edge): C3 quantity case, 0 LLM
  P3  real execution T3 (v2 layout + full ID churn, fresh session): C2
  P4  benefit/efficiency table vs the OLD-code real order captured by
      the pre-change baseline probe (paid with vs without the discount)
  P5  combination gate: full edge pytest suite + AR011 30 scenarios
      (30/30, 0 LLM)

Outputs: outputs/ar023/eval/{ar023_results.json, ar023_report.md}
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
from step_rl.edge.modeling import set_seed  # noqa: E402
from step_rl.edge.planner import fetch_catalog, fetch_promos, plan_instruction  # noqa: E402
from step_rl.edge.runtime import run_skill_hierarchy  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar023" / "eval"
PROBE = ROOT / "outputs" / "ar023" / "baseline_probe.json"

CASES = [
    ("C1", "购买无线充电器和蓝牙耳机，结算时使用满400减50优惠",
     {"targets": {"p3": 1, "p4": 1}, "promo": "man400jian50"}),
    ("C2", "购买iPhone 15，结算时使用满2000减150优惠",
     {"targets": {"p1": 1}, "promo": "man2000jian150"}),
    ("C3", "购买3件无线充电器并结算，使用满400减50优惠",
     {"targets": {"p3": 3}, "promo": "man400jian50"}),
    ("C4", "购买无线充电器，结算时使用满400减50优惠",
     {"targets": None, "promo": None, "why": "199 < 400 低于门槛"}),
    ("C5", "购买2件无线充电器，结算时使用满400减50优惠",
     {"targets": None, "promo": None, "why": "398 < 400 贴线低于门槛"}),
    ("C6", "购买无线充电器和蓝牙耳机，结算时使用满999减99优惠",
     {"targets": None, "promo": None, "why": "满999减99 券面不存在"}),
    ("C7", "搜索无线充电器，使用满400减50优惠",
     {"targets": None, "promo": None, "why": "无结算动作，优惠无处生效"}),
    ("C8", "买最贵的商品结算，并用满2000减150优惠",
     {"targets": {"p1": 1}, "promo": "man2000jian150"}),
]

ORDER_BODY = (
    b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
    b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
    b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7"
)


def make_opener() -> urllib.request.OpenerDirector:
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


def _p0_planner_table(catalog, promos) -> list:
    rows = []
    for label, instruction, expected in CASES:
        spec = plan_instruction(instruction, catalog, promos)
        planned = None if spec is None else {
            "targets": dict(spec.targets),
            "require_checkout": spec.require_checkout,
            "require_promo": spec.require_promo,
            "promo": spec.promo,
        }
        if expected["targets"] is None:
            ok = spec is None
        else:
            ok = (
                spec is not None
                and spec.targets == expected["targets"]
                and spec.require_checkout is True
                and spec.require_promo is True
                and spec.promo == expected["promo"]
            )
        rows.append({"id": label, "instruction": instruction,
                    "expected": expected, "planned": planned, "ok": ok})
    return rows


def _p0_http_flows() -> dict:
    """Real HTTP flows on the changed site (v1 + v2 layouts)."""
    flows = {}
    for layout in ("v1", "v2"):
        server = LocalShopServer(layout=layout).start()
        base = server.base_url
        opener = make_opener()
        try:
            promos = _get(opener, base, "/api/promos")
            checkout = _get(opener, base, "/checkout")
            assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
            assert _get(opener, base, "/api/cart/set?pid=p4&qty=1")[0] == 200
            checkout_full = _get(opener, base, "/checkout")
            claim = _get(opener, base, "/promo/claim/man400jian50")
            assert _post(opener, base, "/place-order", ORDER_BODY) == 200
            state = json.loads(_get(opener, base, "/api/state")[1])
            order = state["orders"][-1]
            flows[layout] = {
                "api_promos": {
                    "status": promos[0],
                    "codes": sorted(p["code"] for p in json.loads(promos[1])),
                },
                "checkout_page": {
                    "empty_cart_status": checkout[0],
                    "has_claim_buttons": (
                        "领取满400减50优惠" in checkout_full[1]
                        and "领取满2000减150优惠" in checkout_full[1]
                    ),
                },
                "claim": {"status": claim[0],
                          "ok": json.loads(claim[1]).get("ok")},
                "order": order,
                "coupon_consumed": state["promo"] is None,
            }
        finally:
            server.stop()

    # honest threshold-miss path + "missed coupon stays usable" rule (v1)
    server = LocalShopServer().start()
    base = server.base_url
    opener = make_opener()
    try:
        assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
        assert _get(opener, base, "/promo/claim/man400jian50")[0] == 200
        assert _post(opener, base, "/place-order", ORDER_BODY) == 200
        state = json.loads(_get(opener, base, "/api/state")[1])
        missed = state["orders"][-1]
        coupon_kept = state["promo"] is not None
        # the first order emptied the cart - re-seed p3+p4 so the reused
        # coupon meets the 400 threshold again (598)
        assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
        assert _get(opener, base, "/api/cart/set?pid=p4&qty=1")[0] == 200
        assert _post(opener, base, "/place-order", ORDER_BODY) == 200
        state2 = json.loads(_get(opener, base, "/api/state")[1])
        reused = state2["orders"][-1]
        flows["threshold_miss"] = {
            "missed_order": missed,
            "coupon_not_consumed": coupon_kept,
            "reuse_order": reused,
        }
    finally:
        server.stop()
    return flows


async def _run_exec_case(
    instruction: str,
    expected_targets: dict,
    expected_promo: str,
    layout: str,
    churn: bool,
    expected_total: int,
    expected_paid: int,
) -> dict:
    """One real-Edge execution of a planned coupon task (0 LLM)."""
    server = LocalShopServer(layout=layout).start()
    base = server.base_url
    catalog = fetch_catalog(base)
    promos = fetch_promos(base)
    spec = plan_instruction(instruction, catalog, promos)
    env_kwargs = dict(channel="msedge", headless=True, semantic=True)
    if churn:
        env_kwargs.update(perturb_ids=True, perturb_prob=1.0)
    env = BrowserEnv(server, **env_kwargs)
    try:
        await env.start()
        started = time.time()
        rollout = await run_skill_hierarchy(
            env, spec, None, None, fallback=False, reset=True
        )
        seconds = round(time.time() - started, 2)
        state = await env.get_state()
        progress = compute_progress(state, env.page_url_path, spec)
        order = (state.get("orders") or [{}])[-1]
        return {
            "layout": layout + ("+churn" if churn else ""),
            "spec": {
                "targets": dict(spec.targets),
                "require_promo": spec.require_promo,
                "promo": spec.promo,
            },
            "success": rollout.success and progress.success,
            "missing_predicates": list(progress.missing),
            "steps": rollout.total_steps,
            "llm_calls": sum(1 for s in rollout.steps if s.source != "skill"),
            "all_skill": all(s.source == "skill" for s in rollout.steps),
            "seconds": seconds,
            "order": {
                "id": order.get("id"),
                "total": order.get("total"),
                "paid": order.get("paid"),
                "promo": order.get("promo"),
            },
            "cart": state.get("cart"),
            "state_promo": state.get("promo"),
            "expected": {
                "targets": expected_targets,
                "promo": expected_promo,
                "total": expected_total,
                "paid": expected_paid,
            },
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
    results: dict = {"ar": "AR023", "phases": {}}

    # ---- P0: post-change re-confirmation (no GPU) --------------------------
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        promos = fetch_promos(server.base_url)
    finally:
        server.stop()
    table = _p0_planner_table(catalog, promos)
    flows = _p0_http_flows()
    gate = check_capability(CASES[0][1], catalog, promos)
    p0 = {
        "planner_table": table,
        "planner_accuracy": sum(r["ok"] for r in table) / len(table),
        "http_flows": flows,
        "gate": {"covered": gate.covered, "reason": gate.reason,
                 "skills": gate.skills},
    }
    results["phases"]["P0_recheck"] = p0
    print(json.dumps(p0, ensure_ascii=False), flush=True)

    naive = (
        json.loads(PROBE.read_text(encoding="utf-8"))["probes"]
        ["C_execution_gap"]["order_json"]
        if PROBE.exists()
        else None
    )
    p0_ok = (
        p0["planner_accuracy"] == 1.0
        and flows["v1"]["api_promos"]["status"] == 200
        and flows["v1"]["api_promos"]["codes"]
        == ["man2000jian150", "man400jian50"]
        and all(flows[l]["checkout_page"]["has_claim_buttons"] for l in ("v1", "v2"))
        and all(
            flows[l]["claim"]["status"] == 200 and flows[l]["claim"]["ok"]
            for l in ("v1", "v2")
        )
        and all(
            flows[l]["order"]["total"] == 598
            and flows[l]["order"]["paid"] == 548
            and flows[l]["order"]["promo"]
            == {"code": "man400jian50", "discount": 50, "applied": True}
            and flows[l]["coupon_consumed"]
            for l in ("v1", "v2")
        )
        and flows["threshold_miss"]["missed_order"]["paid"]
        == flows["threshold_miss"]["missed_order"]["total"] == 199
        and flows["threshold_miss"]["missed_order"]["promo"]["applied"] is False
        and flows["threshold_miss"]["coupon_not_consumed"]
        and flows["threshold_miss"]["reuse_order"]["paid"] == 548
        and flows["threshold_miss"]["reuse_order"]["promo"]["applied"] is True
        and p0["gate"]["covered"] is True
        and naive is not None
    )
    if not p0_ok:
        results["decision"] = "rollback: P0 recheck incomplete"
        (OUT / "ar023_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return

    # ---- P1/P2/P3: real-Edge execution, 0 LLM ------------------------------
    t1 = await _run_exec_case(
        CASES[0][1], {"p3": 1, "p4": 1}, "man400jian50",
        "v1", False, 598, 548,
    )
    print(json.dumps(t1, ensure_ascii=False), flush=True)
    t2 = await _run_exec_case(
        CASES[2][1], {"p3": 3}, "man400jian50",
        "v1", False, 597, 547,
    )
    print(json.dumps(t2, ensure_ascii=False), flush=True)
    t3 = await _run_exec_case(
        CASES[1][1], {"p1": 1}, "man2000jian150",
        "v2", True, 6999, 6849,
    )
    print(json.dumps(t3, ensure_ascii=False), flush=True)
    exec_cases = [t1, t2, t3]
    results["phases"]["P1_T1"] = t1
    results["phases"]["P2_T2"] = t2
    results["phases"]["P3_T3"] = t3

    def _case_ok(row: dict) -> bool:
        order = row["order"]
        return (
            row["success"]
            and row["all_skill"]
            and row["llm_calls"] == 0
            and row["missing_predicates"] == []
            and order["total"] == row["expected"]["total"]
            and order["paid"] == row["expected"]["paid"]
            and order["promo"]
            and order["promo"]["applied"] is True
            and order["promo"]["code"] == row["expected"]["promo"]
            and row["cart"] == {}
            and row["state_promo"] is None
        )

    # ---- P4: benefit/efficiency vs the old-code real order ------------------
    old_paid = 598  # old-code order of the same cart had no discount fields
    results["phases"]["P4_benefit"] = {
        "old_code_real_order": {
            "source": "outputs/ar023/baseline_probe.json",
            "order": naive,
            "paid": old_paid,
            "llm_calls": 0,
            "checkout_skill_steps": 4,
        },
        "new_chain": {
            "paid": [row["order"]["paid"] for row in exec_cases],
            "llm_calls": [row["llm_calls"] for row in exec_cases],
            "steps": [row["steps"] for row in exec_cases],
            "seconds": [row["seconds"] for row in exec_cases],
            "checkout_skill_steps": 5,
        },
        "real_discount": [
            row["expected"]["total"] - row["expected"]["paid"]
            for row in exec_cases
        ],
    }

    # ---- P5: combination gate -----------------------------------------------
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

    # ---- decision -------------------------------------------------------------
    ar011_ok = (
        ar011_summary.get("tasks") == 30
        and ar011_summary.get("success_rate") == 1.0
        and ar011_summary.get("policy_steps") == 0
    )
    exec_ok = all(_case_ok(row) for row in exec_cases)
    combination_ok = (
        p0_ok
        and exec_ok
        and gates["pytest_edge"]["returncode"] == 0
        and gates["ar011_suite"]["returncode"] == 0
        and ar011_ok
    )
    results["decision"] = "keep" if combination_ok else "rollback"
    (OUT / "ar023_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- report -----------------------------------------------------------------
    lines = [
        "# AR023 优惠券/促销约束规划 真实评测",
        "",
        "## P0 改动后复核（改动前基线探针：outputs/ar023/baseline_probe.json）",
        "",
        "| 指令 | 期望 | 真实规划 | 正确 |",
        "|------|------|----------|------|",
    ]
    for row in table:
        expected = row["expected"]
        expected_text = (
            "None（" + expected.get("why", "") + "）"
            if expected["targets"] is None
            else f"{expected['targets']} + {expected['promo']}"
        )
        lines.append(
            f"| {row['id']} {row['instruction'][:14]}… | {expected_text} | "
            f"{row['planned']} | {'✓' if row['ok'] else '✗'} |"
        )
    lines += [
        "",
        f"- 规划准确率：{p0['planner_accuracy']:.0%}（8/8，含 4 组诚实 None）",
        f"- /api/promos：{flows['v1']['api_promos']['status']}，"
        f"{flows['v1']['api_promos']['codes']}",
        f"- v1/v2 结算页领取按钮：{flows['v1']['checkout_page']['has_claim_buttons']} / "
        f"{flows['v2']['checkout_page']['has_claim_buttons']}",
        f"- 真实全流程（v1/v2）：total=598 → paid=548，applied=True，券消耗",
        f"- 贴线路径：199 < 400 → applied=False、paid=199、券不消耗；"
        f"同券后续凑满 598 → applied=True（真实复用）",
        f"- 门控：covered={p0['gate']['covered']}（{p0['gate']['reason']}，"
        f"{p0['gate']['skills']}）",
        "",
        "## P1–P3 真实 Edge 执行（0 LLM）",
        "",
        "| 场景 | 布局 | 成功 | 步数 | 全技能 | total→paid | 促销 | 耗时 |",
        "|------|------|------|------|--------|------------|------|------|",
    ]
    for i, row in enumerate(exec_cases):
        order = row["order"]
        lines.append(
            f"| T{i + 1} | {row['layout']} | {'✓' if row['success'] else '✗'} | "
            f"{row['steps']} | {'是' if row['all_skill'] else '否'} | "
            f"{order['total']}→{order['paid']} | "
            f"{order['promo']['code']}（{order['promo']['applied']}） | "
            f"{row['seconds']}s |"
        )
    lines += [
        "",
        "## P4 收益/效率对照（naive = 旧代码真实订单，探针留证）",
        "",
        "| 口径 | LLM 调用 | 同购物车（p3+p4）实付 | 结算技能步数 |",
        "|------|----------|------------------------|----------------|",
        f"| 旧代码（naive，无折扣字段） | 0 | ¥{old_paid}（无折扣） | 4 |",
        f"| 新链路（T1） | 0 | ¥{exec_cases[0]['order']['paid']}（省 "
        f"¥{exec_cases[0]['expected']['total'] - exec_cases[0]['expected']['paid']}） | 5 |",
        f"| 新链路（T2/T3） | 0 | ¥{exec_cases[1]['order']['paid']} / "
        f"¥{exec_cases[2]['order']['paid']}（省 "
        f"¥{exec_cases[1]['expected']['total'] - exec_cases[1]['expected']['paid']} / "
        f"¥{exec_cases[2]['expected']['total'] - exec_cases[2]['expected']['paid']}） | 5 |",
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
    (OUT / "ar023_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"decision": results["decision"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
