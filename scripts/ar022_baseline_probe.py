"""AR022 pre-change baseline probe (run on the AR021 code state).

Evidence for the three gaps that AR022 closes, measured on the real
planner, the real HTTP server and the real skill registry:

  A  planner gap: ``plan_instruction("查询我最近的订单状态")`` returns
     None (planner_unsupported), so the composed runtime fails
     explicitly with fallback_required=True;
  B  site gap: a real ``GET /orders`` returns HTTP 404 (页面不存在) -
     there is no order list page, and the single-order success page
     carries no status field;
  C  registry gap: no ``order_query`` operation exists in the induced
     skill registry, so even a one-off LLM success would have nowhere
     to be induced (AR019 chain cannot take over).

Outputs: outputs/ar022/baseline_probe.json + baseline_probe.md
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

from step_rl.edge.capability import check_capability  # noqa: E402
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    induced_operations,
)

OUT = ROOT / "outputs" / "ar022"

INSTRUCTION = "查询我最近的订单状态"
INSTRUCTION_CANCELLED = "查看我最近取消的订单状态"


def make_opener() -> urllib.request.OpenerDirector:
    """A cookie-persistent opener so the shop session (sid) survives."""
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def get(opener: urllib.request.OpenerDirector, base: str, path: str) -> tuple[int, str]:
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
        "ar": "AR022",
        "note": "pre-change baseline probe (AR021 code state)",
        "probes": {},
    }

    # ---- A: planner gap ----------------------------------------------------
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
    finally:
        server.stop()
    spec_active = plan_instruction(INSTRUCTION, catalog)
    spec_cancelled = plan_instruction(INSTRUCTION_CANCELLED, catalog)
    gate = check_capability(INSTRUCTION, catalog)
    probe_a = {
        "plan_active_is_none": spec_active is None,
        "plan_cancelled_is_none": spec_cancelled is None,
        "gate": {
            "covered": gate.covered,
            "reason": gate.reason,
            "skills": gate.skills,
        },
    }
    probe_a["planner_unsupported"] = (
        spec_active is None and gate.reason == "planner_unsupported"
    )
    results["probes"]["A_planner_gap"] = probe_a
    print(json.dumps(probe_a, ensure_ascii=False), flush=True)

    # ---- B: site gap (real HTTP, one persistent session) ----------------------
    server = LocalShopServer().start()
    base = server.base_url
    opener = make_opener()
    try:
        # build a real order so the probe can also inspect the success page
        cart = get(opener, base, "/api/cart/set?pid=p3&qty=2")
        order_page_status = post(
            opener,
            base,
            "/place-order",
            b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
            b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
            b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7",
        )
        state = json.loads(get(opener, base, "/api/state")[1])
        orders = state.get("orders", [])
        order_id = orders[-1]["id"] if orders else ""
        orders_route = get(opener, base, "/orders")
        single_page = get(opener, base, f"/order/{order_id}")
    finally:
        server.stop()
    probe_b = {
        "orders_route_status": orders_route[0],
        "orders_route_body": orders_route[1][:200],
        "single_order_page_has_status_text": (
            "有效" in single_page[1] or "已取消" in single_page[1]
        ),
        "cart_seed_status": cart[0],
        "order_created": bool(orders),
        "order_status_field": orders[-1].get("status") if orders else None,
        "order_page_status": order_page_status,
    }
    results["probes"]["B_site_gap"] = probe_b
    print(json.dumps(probe_b, ensure_ascii=False), flush=True)

    # ---- C: registry gap -----------------------------------------------------
    clear_induced_skills()
    probe_c = {
        "induced_operations": induced_operations(),
        "has_order_query": "order_query" in induced_operations(),
    }
    results["probes"]["C_registry_gap"] = probe_c
    print(json.dumps(probe_c, ensure_ascii=False), flush=True)

    (OUT / "baseline_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR022 改动前基线探针（AR021 代码状态）",
        "",
        f"- A 规划器缺口：`{INSTRUCTION}` → plan_instruction=None，"
        f"check_capability → covered={probe_a['gate']['covered']}，"
        f"reason={probe_a['gate']['reason']}",
        f"- B 站点缺口：真实 `GET /orders` → HTTP {probe_b['orders_route_status']}"
        f"（{probe_b['orders_route_body'][:40]}）；"
        f"单订单成功页含状态文案={probe_b['single_order_page_has_status_text']}"
        f"（服务端订单 status 字段={probe_b['order_status_field']}，"
        f"但页面不渲染状态）",
        f"- C 注册表缺口：induced_operations={probe_c['induced_operations']}，"
        f"order_query 落点={probe_c['has_order_query']}",
        "",
        "结论：订单状态查询在规划、站点、技能落点三层均无支撑，"
        "组合运行时对该指令显式失败（planner_unsupported / fallback_required）。",
    ]
    (OUT / "baseline_probe.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"done": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
