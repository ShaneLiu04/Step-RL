"""AR023 pre-change baseline probe (run on the AR022 code state).

Evidence for the gaps that AR023 closes, measured on the real planner,
the real HTTP server and the real compiled skills:

  A  silent constraint drop: all 8 promo instructions compile on the
     OLD planner into "success" specs with no promo constraint; the 4
     infeasible ones (199 < 400, 398 < 400 near-miss, fictitious
     满999减99, no-checkout) are still compiled as if the coupon did
     not matter - constraint dropped, success kept (the silent
     downgrade AGENTS.md §1 forbids);
  B  site gap: real ``GET /api/promos`` -> 404; the v1/v2 checkout
     pages carry no 领取…优惠 element;
  C  execution gap: a real session builds cart p3+p4, places a real
     order on the old code - the order JSON has no total/paid/promo
     fields; the old compiled checkout skill has no claim step; the
     old verifier predicate table has no order_promo_applied.

Outputs: outputs/ar023/baseline_probe.json + baseline_probe.md
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import checkout_skill  # noqa: E402
from step_rl.edge.verifier import _predicates  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402

OUT = ROOT / "outputs" / "ar023"

# 8 real instructions with the user-expected outcome (live prices:
# p1=6999 / p2=59 / p3=199 / p4=399; promos: 满400减50, 满2000减150)
CASES = [
    ("C1", "购买无线充电器和蓝牙耳机，结算时使用满400减50优惠",
     {"targets": {"p3": 1, "p4": 1}, "promo": "man400jian50"}),
    ("C2", "购买iPhone 15，结算时使用满2000减150优惠",
     {"targets": {"p1": 1}, "promo": "man2000jian150"}),
    ("C3", "购买3件无线充电器并结算，使用满400减50优惠",
     {"targets": {"p3": 3}, "promo": "man400jian50"}),
    ("C4", "购买无线充电器，结算时使用满400减50优惠",
     {"targets": None, "promo": None,
      "infeasible_reason": "199 < 400 总额低于门槛"}),
    ("C5", "购买2件无线充电器，结算时使用满400减50优惠",
     {"targets": None, "promo": None,
      "infeasible_reason": "398 < 400 贴线低于门槛"}),
    ("C6", "购买无线充电器和蓝牙耳机，结算时使用满999减99优惠",
     {"targets": None, "promo": None,
      "infeasible_reason": "满999减99 券面不存在"}),
    ("C7", "搜索无线充电器，使用满400减50优惠",
     {"targets": None, "promo": None,
      "infeasible_reason": "无结算动作，优惠无处生效"}),
    ("C8", "买最贵的商品结算，并用满2000减150优惠",
     {"targets": {"p1": 1}, "promo": "man2000jian150"}),
]


def make_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )


def get(
    opener: urllib.request.OpenerDirector, base: str, path: str
) -> tuple[int, str]:
    try:
        with opener.open(base + path) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def post(
    opener: urllib.request.OpenerDirector, base: str, path: str, data: bytes
) -> int:
    try:
        with opener.open(
            urllib.request.Request(base + path, data=data, method="POST")
        ) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict = {
        "ar": "AR023",
        "note": "pre-change baseline probe (AR022 code state)",
        "probes": {},
    }

    # ---- A: silent constraint drop (real old planner) -------------------
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
    finally:
        server.stop()
    rows = []
    for label, instruction, expected in CASES:
        spec = plan_instruction(instruction, catalog)
        planned = None if spec is None else {
            "targets": dict(spec.targets),
            "require_checkout": spec.require_checkout,
            "level": spec.level,
        }
        # Old TaskSpec has no promo fields at all: the constraint cannot
        # even be represented in the plan.
        row = {
            "id": label,
            "instruction": instruction,
            "expected": expected,
            "old_planned": planned,
            "spec_has_promo_fields": bool(
                hasattr(spec, "require_promo") if spec is not None else False
            ),
        }
        row["silent_drop"] = (
            planned is not None
            and expected["targets"] is None
        )  # infeasible yet compiled as a "success" plan
        rows.append(row)
        print(
            f"[A] {label} planned={planned} "
            f"silent_drop={row['silent_drop']}",
            flush=True,
        )
    results["probes"]["A_silent_drop"] = rows
    silent = [r["id"] for r in rows if r["silent_drop"]]
    results["probes"]["A_summary"] = {
        "infeasible_still_compiled": silent,
        "constraint_representable": any(
            r["spec_has_promo_fields"] for r in rows
        ),
    }

    # ---- B: site gap (real HTTP, both layouts) ---------------------------
    opener = make_opener()
    probes_b: dict = {}
    for layout in ("v1", "v2"):
        server = LocalShopServer(layout=layout).start()
        try:
            status, body = get(opener, server.base_url, "/checkout")
            probes_b[layout] = {
                "checkout_status": status,
                "has_claim_element": "领取" in body and "优惠" in body,
            }
        finally:
            server.stop()
    server = LocalShopServer().start()
    try:
        promos_status, promos_body = get(opener, server.base_url, "/api/promos")
    finally:
        server.stop()
    probes_b["api_promos"] = {
        "status": promos_status,
        "body": promos_body[:120],
    }
    results["probes"]["B_site_gap"] = probes_b
    print(json.dumps(probes_b, ensure_ascii=False), flush=True)

    # ---- C: execution gap (real session, old code) -----------------------
    server = LocalShopServer().start()
    base = server.base_url
    opener2 = make_opener()
    try:
        get(opener2, base, "/api/cart/set?pid=p3&qty=1")
        get(opener2, base, "/api/cart/set?pid=p4&qty=1")
        place_status = post(
            opener2,
            base,
            "/place-order",
            b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
            b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
            b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7",
        )
        state = json.loads(get(opener2, base, "/api/state")[1])
    finally:
        server.stop()
    order = (state.get("orders") or [{}])[-1]
    placeholder = TaskSpec(
        task_id="probe", level=4, goal="", search_query="",
        targets={"p3": 1}, require_checkout=True,
    )
    predicate_names = sorted(_predicates(placeholder).keys())
    checkout_steps = [
        {"kind": s.kind, "name": s.name} for s in checkout_skill().steps
    ]
    results["probes"]["C_execution_gap"] = {
        "place_order_status": place_status,
        "order_json": order,
        "order_has_total_paid_promo": {
            "total": "total" in order,
            "paid": "paid" in order,
            "promo": "promo" in order,
        },
        "old_checkout_skill_steps": checkout_steps,
        "old_checkout_skill_has_claim_step": any(
            "领取" in s["name"] for s in checkout_steps
        ),
        "verifier_has_order_promo_applied": (
            "order_promo_applied" in predicate_names
        ),
        "verifier_predicate_names": predicate_names,
    }
    print(
        json.dumps(results["probes"]["C_execution_gap"], ensure_ascii=False),
        flush=True,
    )

    (OUT / "baseline_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    a_summary = results["probes"]["A_summary"]
    c = results["probes"]["C_execution_gap"]
    lines = [
        "# AR023 改动前基线探针（AR022 代码状态）",
        "",
        f"- A 规划器静默丢约束：8 条优惠券指令全部编译出无促销约束的 spec"
        f"（TaskSpec 无 require_promo/promo 字段，约束在计划中不可表示）；"
        f"不可行指令被照常编译成「成功计划」：{a_summary['infeasible_still_compiled']}",
        f"- B 站点缺口：`GET /api/promos` → HTTP {probes_b['api_promos']['status']}"
        f"（{probes_b['api_promos']['body'][:24]}）；v1 结算页含领取元素="
        f"{probes_b['v1']['has_claim_element']}，v2="
        f"{probes_b['v2']['has_claim_element']}",
        f"- C 执行缺口：旧代码真实下单（cart p3+p4，HTTP {place_status}）订单 JSON"
        f"={'total/paid/promo 字段: ' + str(c['order_has_total_paid_promo'])}；"
        f"旧编译结算技能 {len(c['old_checkout_skill_steps'])} 步无领取步；"
        f"旧验证器谓词表含 order_promo_applied="
        f"{c['verifier_has_order_promo_applied']}",
        "",
        "结论：满减券约束在规划（静默丢弃）、站点（无券无折扣结算）、"
        "执行（无领取步、无谓词）三层均无支撑；旧路径对不可行指令"
        "「丢约束、保成功」，属 AGENTS.md §1 禁止的静默降级。",
    ]
    (OUT / "baseline_probe.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"done": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
