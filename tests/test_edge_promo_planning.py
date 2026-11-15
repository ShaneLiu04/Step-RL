"""AR023 promo constraint planning tests (planner / tasks / decomposition /
skill / verifier / real HTTP / real browser).
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import pytest

from step_rl.edge.capability import check_capability
from step_rl.edge.hierarchical import decompose_task
from step_rl.edge.planner import fetch_catalog, fetch_promos, plan_instruction
from step_rl.edge.skill_library import (
    checkout_skill,
    clear_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.skill_stats import clear_skill_stats
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress

C1 = "购买无线充电器和蓝牙耳机，结算时使用满400减50优惠"
C2 = "购买iPhone 15，结算时使用满2000减150优惠"
C3 = "购买3件无线充电器并结算，使用满400减50优惠"
C4 = "购买无线充电器，结算时使用满400减50优惠"
C5 = "购买2件无线充电器，结算时使用满400减50优惠"
C6 = "购买无线充电器和蓝牙耳机，结算时使用满999减99优惠"
C7 = "搜索无线充电器，使用满400减50优惠"
C8 = "买最贵的商品结算，并用满2000减150优惠"


@pytest.fixture(autouse=True)
def _clean_registry_and_stats():
    clear_induced_skills()
    clear_skill_stats()
    yield
    clear_induced_skills()
    clear_skill_stats()


@pytest.fixture(scope="module")
def shop():
    from step_rl.edge.site import LocalShopServer

    server = LocalShopServer().start()
    try:
        yield {
            "base": server.base_url,
            "catalog": fetch_catalog(server.base_url),
            "promos": fetch_promos(server.base_url),
        }
    finally:
        server.stop()


def plan(instruction: str, shop: dict):
    return plan_instruction(instruction, shop["catalog"], shop["promos"])


# ---------------------------------------------------------------------------
# planner: feasible coupons
# ---------------------------------------------------------------------------


def test_planner_feasible_multi(shop):
    spec = plan(C1, shop)
    assert spec is not None
    assert spec.targets == {"p3": 1, "p4": 1}
    assert spec.require_checkout is True
    assert spec.require_promo is True
    assert spec.promo == "man400jian50"
    names = spec.predicate_names()
    assert names[-1] == "order_promo_applied"
    assert names[:-1] == [
        "search_done",
        "product_viewed",
        "cart_contains",
        "cart_viewed",
        "checkout_viewed",
        "name_filled",
        "address_filled",
        "order_placed",
    ]


def test_planner_feasible_big_promo(shop):
    spec = plan(C2, shop)
    assert spec is not None
    assert spec.targets == {"p1": 1}
    assert spec.require_promo is True
    assert spec.promo == "man2000jian150"


def test_planner_feasible_quantity(shop):
    # 3 x 199 = 597 >= 400 - feasible by live catalog price
    spec = plan(C3, shop)
    assert spec is not None
    assert spec.targets == {"p3": 3}
    assert spec.promo == "man400jian50"


def test_planner_no_mention_branch(shop):
    # C8 has no product mention: the cheapest/most-explicit branch picks p1
    spec = plan(C8, shop)
    assert spec is not None
    assert spec.targets == {"p1": 1}
    assert spec.promo == "man2000jian150"


# ---------------------------------------------------------------------------
# planner: infeasible coupons must refuse explicitly (never silent drop)
# ---------------------------------------------------------------------------


def test_planner_below_threshold_none(shop):
    # 199 < 400: infeasible - explicit refusal, not a silent constraint drop
    assert plan(C4, shop) is None


def test_planner_near_miss_none(shop):
    # 398 < 400: one yuan short of the threshold proves live-price math
    assert plan(C5, shop) is None


def test_planner_unknown_promo_face_none(shop):
    # 满999减99 does not exist in the live list - never guess a face
    assert plan(C6, shop) is None


def test_planner_no_checkout_none(shop):
    # a coupon cannot take effect without a placed order
    assert plan(C7, shop) is None


def test_planner_generic_coupon_none(shop):
    # 优惠券 without a 满X减Y face cannot be matched to a real coupon
    spec = plan("购买无线充电器和蓝牙耳机，使用优惠券结算", shop)
    assert spec is None


def test_planner_without_live_promos_none(shop):
    # no live promo list -> no verification possible -> explicit refusal
    spec = plan_instruction(C1, shop["catalog"], None)
    assert spec is None


# ---------------------------------------------------------------------------
# planner regression guards (non-coupon behaviour unchanged)
# ---------------------------------------------------------------------------


def test_planner_plain_checkout_regression(shop):
    spec = plan("购买无线充电器和蓝牙耳机并结算", shop)
    assert spec is not None
    assert spec.targets == {"p3": 1, "p4": 1}
    assert spec.require_promo is False
    assert spec.promo == ""
    assert "order_promo_applied" not in spec.predicate_names()


def test_planner_order_query_regression(shop):
    spec = plan("查询我最近的订单状态", shop)
    assert spec is not None
    assert spec.operation == "order_query"
    assert spec.require_promo is False


# ---------------------------------------------------------------------------
# TaskSpec / verifier / decomposition
# ---------------------------------------------------------------------------


def test_predicate_names_plain_checkout_unchanged():
    task = TaskSpec(
        task_id="t",
        level=4,
        goal="",
        search_query="x",
        targets={"p3": 1},
        require_checkout=True,
    )
    assert task.predicate_names() == [
        "search_done",
        "product_viewed",
        "cart_contains",
        "cart_viewed",
        "checkout_viewed",
        "name_filled",
        "address_filled",
        "order_placed",
    ]


def _full_state(order: dict) -> dict:
    """A real /api/state shape with every checkout-chain predicate true."""
    return {
        "order": order,
        "orders": [order],
        "cart": {},
        "form": {"name": "刘星言先生", "address": "深圳市龙岗区坂田路1号"},
        "visited": [
            "/",
            "/search?q=无线",
            "/product/p3",
            "/cart",
            "/checkout",
        ],
    }


def test_verifier_order_promo_applied():
    task = TaskSpec(
        task_id="t",
        level=4,
        goal="",
        search_query="x",
        targets={"p3": 1},
        require_checkout=True,
        require_promo=True,
        promo="man400jian50",
    )
    good_order = {
        "id": "o1",
        "items": {"p3": 1},
        "status": "active",
        "total": 199,
        "paid": 149,
        "promo": {"code": "man400jian50", "discount": 50, "applied": True},
    }
    assert compute_progress(_full_state(good_order), "/order/o1", task).success

    wrong_code = json.loads(json.dumps(good_order))
    wrong_code["promo"]["code"] = "man2000jian150"
    assert compute_progress(_full_state(wrong_code), "/order/o1", task).success is False

    missed = json.loads(json.dumps(good_order))
    missed["promo"]["applied"] = False
    missed["promo"]["discount"] = 0
    missed["paid"] = missed["total"]
    assert compute_progress(_full_state(missed), "/order/o1", task).success is False

    no_promo = json.loads(json.dumps(good_order))
    no_promo["id"] = "o2"
    no_promo["promo"] = None
    no_promo["paid"] = no_promo["total"]
    assert compute_progress(_full_state(no_promo), "/order/o2", task).success is False


def test_decompose_propagates_promo(shop):
    spec = plan(C1, shop)
    subtasks = decompose_task(spec)
    checkout = [t for t in subtasks if t.require_checkout]
    assert len(checkout) == 1
    sub = checkout[0]
    assert sub.require_promo is True
    assert sub.promo == "man400jian50"
    assert "order_promo_applied" in sub.predicate_names()
    # add subtasks stay promo-free
    for other in subtasks:
        if not other.require_checkout:
            assert other.require_promo is False
            assert other.promo == ""


# ---------------------------------------------------------------------------
# compiled checkout skill
# ---------------------------------------------------------------------------


def test_checkout_skill_with_promo():
    skill = checkout_skill("man400jian50")
    names = [s.name for s in skill.steps]
    assert names == [
        "",
        "收货人",
        "地址",
        "领取满400减50优惠",
        "提交订单",
    ]
    claim = skill.steps[3]
    assert claim.kind == "click" and claim.role == "button"
    assert "领取满2000减150优惠" in [
        s.name for s in checkout_skill("man2000jian150").steps
    ]


def test_checkout_skill_without_promo_field_for_field():
    steps = [(s.kind, s.name, s.role, s.value, s.url) for s in checkout_skill().steps]
    assert steps == [
        ("goto", "", "", "", "/checkout"),
        ("type", "收货人", "textbox", "刘星言先生", ""),
        ("type", "地址", "textbox", "深圳市龙岗区坂田路1号", ""),
        ("click", "提交订单", "button", "", ""),
    ]
    # unknown codes are ignored, not fabricated into a claim step
    assert len(checkout_skill("man999jian99").steps) == 4


def test_skill_for_subtask_routes_promo():
    plain = TaskSpec(
        task_id="t",
        level=4,
        goal="",
        search_query="x",
        targets={"p3": 1},
        require_checkout=True,
    )
    promo = TaskSpec(
        task_id="t",
        level=4,
        goal="",
        search_query="x",
        targets={"p3": 1},
        require_checkout=True,
        require_promo=True,
        promo="man400jian50",
    )
    assert len(skill_for_subtask(plain).steps) == 4
    routed = skill_for_subtask(promo)
    assert any(s.name == "领取满400减50优惠" for s in routed.steps)


# ---------------------------------------------------------------------------
# capability gate
# ---------------------------------------------------------------------------


def test_capability_gate_promo(shop):
    gate = check_capability(C1, shop["catalog"], shop["promos"])
    assert gate.covered is True
    assert "checkout" in gate.skills
    # without the live promo list the coupon instruction is refused
    gate_no_promos = check_capability(C1, shop["catalog"])
    assert gate_no_promos.covered is False
    assert gate_no_promos.reason == "planner_unsupported"


# ---------------------------------------------------------------------------
# real HTTP: full promo flow (no browser)
# ---------------------------------------------------------------------------


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


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


def test_real_http_promo_full_flow():
    from step_rl.edge.site import LocalShopServer

    ORDER = (
        b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
        b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
        b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7"
    )
    for layout in ("v1", "v2"):
        server = LocalShopServer(layout=layout).start()
        base = server.base_url
        opener = _opener()
        try:
            promos = _get(opener, base, "/api/promos")
            assert promos[0] == 200
            parsed = json.loads(promos[1])
            assert {p["code"] for p in parsed} == {
                "man400jian50",
                "man2000jian150",
            }

            # unknown codes are refused
            assert _get(opener, base, "/promo/claim/man999jian99")[0] == 404

            # real session: cart p3+p4 = 598 first, then the checkout page
            assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
            assert _get(opener, base, "/api/cart/set?pid=p4&qty=1")[0] == 200

            # both checkout layouts render the real claim buttons
            checkout = _get(opener, base, "/checkout")
            assert checkout[0] == 200
            assert "领取满400减50优惠" in checkout[1]
            assert "领取满2000减150优惠" in checkout[1]

            # claiming is a no-navigation AJAX call (JSON ack)
            claim = _get(opener, base, "/promo/claim/man400jian50")
            assert claim[0] == 200 and json.loads(claim[1])["ok"] is True
            state_before = json.loads(_get(opener, base, "/api/state")[1])
            assert state_before["promo"] == {
                "code": "man400jian50",
                "threshold": 400,
                "discount": 50,
            }
            assert _post(opener, base, "/place-order", ORDER) == 200
            state = json.loads(_get(opener, base, "/api/state")[1])
            order = state["orders"][-1]
            assert order["total"] == 598
            assert order["paid"] == 548
            assert order["promo"] == {
                "code": "man400jian50",
                "discount": 50,
                "applied": True,
            }
            # applied coupon is consumed
            assert state["promo"] is None

            # the order page really renders the settled discount
            success_page = _get(opener, base, f"/order/{order['id']}")
            assert "548" in success_page[1] and "优惠已抵扣" in success_page[1]
        finally:
            server.stop()


def test_real_http_threshold_miss_keeps_coupon():
    from step_rl.edge.site import LocalShopServer

    ORDER = (
        b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
        b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
        b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7"
    )
    server = LocalShopServer().start()
    base = server.base_url
    opener = _opener()
    try:
        # 199 < 400: claimed but the threshold is missed -> applied=False
        assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
        assert _get(opener, base, "/promo/claim/man400jian50")[0] == 200
        assert _post(opener, base, "/place-order", ORDER) == 200
        state = json.loads(_get(opener, base, "/api/state")[1])
        order = state["orders"][-1]
        assert order["paid"] == order["total"] == 199
        assert order["promo"] == {
            "code": "man400jian50",
            "discount": 0,
            "applied": False,
        }
        # the coupon was NOT consumed - a later bigger order still uses it
        assert state["promo"] is not None
        assert _get(opener, base, "/api/cart/set?pid=p4&qty=1")[0] == 200
        assert _get(opener, base, "/api/cart/set?pid=p3&qty=1")[0] == 200
        assert _post(opener, base, "/place-order", ORDER) == 200
        state2 = json.loads(_get(opener, base, "/api/state")[1])
        order2 = state2["orders"][-1]
        assert order2["total"] == 598 and order2["paid"] == 548
        assert order2["promo"]["applied"] is True
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# real browser (Playwright + system Edge): full C1 chain, 0 LLM
# ---------------------------------------------------------------------------


def test_real_browser_promo_checkout_chain():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.runtime import run_skill_hierarchy
    from step_rl.edge.site import LocalShopServer

    server = LocalShopServer().start()
    base = server.base_url
    catalog = fetch_catalog(base)
    promos = fetch_promos(base)
    spec = plan_instruction(C1, catalog, promos)
    assert spec is not None and spec.require_promo

    async def runner():
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            await env.start()
            rollout = await run_skill_hierarchy(
                env, spec, None, None, fallback=False, reset=True
            )
            state = await env.get_state()
            progress = compute_progress(state, env.page_url_path, spec)
            assert rollout.success and progress.success
            assert rollout.total_steps > 0
            assert all(s.source == "skill" for s in rollout.steps)
            order = state["orders"][-1]
            assert order["promo"]["applied"] is True
            assert order["promo"]["code"] == "man400jian50"
            assert order["total"] == 598 and order["paid"] == 548
            assert state["promo"] is None
        finally:
            await env.close()

    asyncio.run(runner())
    server.stop()
