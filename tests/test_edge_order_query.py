"""AR022 order status query tests (planner / verifier / gate / site / browser)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import pytest

from step_rl.edge.capability import check_capability
from step_rl.edge.planner import fetch_catalog, plan_instruction
from step_rl.edge.skill_library import (
    clear_induced_skills,
    register_induced_skill,
    skill_for_subtask,
)
from step_rl.edge.skill_stats import clear_skill_stats, get_skill_stat
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress

INSTRUCTION_ACTIVE = "查询我最近的订单状态"
INSTRUCTION_CANCELLED = "查看我最近取消的订单状态"
CHECKOUT_INSTRUCTION = "完成结算并提交订单"

# The expected induced template shape: header link to the order list page.
QUERY_TEMPLATE = [
    {"kind": "click", "role": "link", "name": "我的订单", "value": ""},
]


@pytest.fixture(autouse=True)
def _clean_registry_and_stats():
    clear_induced_skills()
    clear_skill_stats()
    yield
    clear_induced_skills()
    clear_skill_stats()


def order_query_task(cancelled: bool = False) -> TaskSpec:
    preds = ["orders_viewed"]
    preds.append("latest_order_cancelled" if cancelled else "latest_order_active")
    return TaskSpec(
        task_id="q",
        level=2,
        goal=INSTRUCTION_CANCELLED if cancelled else INSTRUCTION_ACTIVE,
        search_query="",
        targets={},
        operation="order_query",
        predicates=preds,
        start_path="/",
    )


@pytest.fixture(scope="module")
def catalog():
    from step_rl.edge.site import LocalShopServer

    server = LocalShopServer().start()
    try:
        return fetch_catalog(server.base_url)
    finally:
        server.stop()


def _state(orders: list, visited: list) -> dict:
    return {"orders": orders, "visited": visited, "cart": {}}


# ---------------------------------------------------------------------------
# planner
# ---------------------------------------------------------------------------


def test_planner_order_query_active(catalog):
    spec = plan_instruction(INSTRUCTION_ACTIVE, catalog)
    assert spec is not None
    assert spec.operation == "order_query"
    assert spec.targets == {}
    assert spec.start_path == "/"
    assert spec.predicates == ["orders_viewed", "latest_order_active"]
    assert spec.predicate_names() == ["orders_viewed", "latest_order_active"]


def test_planner_order_query_cancelled(catalog):
    spec = plan_instruction(INSTRUCTION_CANCELLED, catalog)
    assert spec is not None
    assert spec.operation == "order_query"
    assert spec.predicates == ["orders_viewed", "latest_order_cancelled"]


def test_planner_checkout_not_misrouted(catalog):
    spec = plan_instruction(CHECKOUT_INSTRUCTION, catalog)
    assert spec is not None
    assert spec.operation != "order_query"
    assert spec.require_checkout is True


def test_planner_query_without_order_not_misrouted(catalog):
    # 查询 alone (no 订单) must not enter the order_query branch
    spec = plan_instruction("查询库存情况", catalog)
    if spec is not None:
        assert spec.operation != "order_query"


# ---------------------------------------------------------------------------
# verifier predicates (real server-state shapes)
# ---------------------------------------------------------------------------


def test_verifier_order_predicates():
    task = order_query_task()
    # no orders: state predicates are False, viewing the page still counts
    state = _state([], ["/", "/orders"])
    result = compute_progress(state, "/orders", task)
    assert "orders_viewed" in result.satisfied
    assert "latest_order_active" in result.missing
    assert not result.success

    active = _state([{"id": "o1", "items": {"p3": 2}, "status": "active"}], ["/orders"])
    assert compute_progress(active, "/orders", task).success
    task_cancelled = order_query_task(cancelled=True)
    assert compute_progress(active, "/orders", task_cancelled).success is False

    cancelled = _state(
        [
            {"id": "o1", "items": {"p3": 2}, "status": "active"},
            {"id": "o2", "items": {"p4": 1}, "status": "cancelled"},
        ],
        ["/orders"],
    )
    result = compute_progress(cancelled, "/orders", task_cancelled)
    assert result.success
    # latest wins: the newest order is cancelled, the older one active
    assert compute_progress(cancelled, "/orders", task).success is False

    # orders_viewed requires the real visit
    state = _state([{"id": "o1", "items": {}, "status": "active"}], ["/", "/cart"])
    assert "orders_viewed" in compute_progress(state, "/cart", task).missing


def test_predicate_names_from_planned_spec(catalog):
    spec = plan_instruction(INSTRUCTION_ACTIVE, catalog)
    assert spec.predicate_names() == ["orders_viewed", "latest_order_active"]


# ---------------------------------------------------------------------------
# capability gate + materialisation (zero code change, D5)
# ---------------------------------------------------------------------------


def test_capability_gap_then_covered(catalog):
    gate_before = check_capability(INSTRUCTION_ACTIVE, catalog)
    assert gate_before.covered is False
    assert gate_before.reason == "no_skill_for_level_2"

    register_induced_skill("order_query", QUERY_TEMPLATE, "induced_order_query")
    gate_after = check_capability(INSTRUCTION_ACTIVE, catalog)
    assert gate_after.covered is True
    assert gate_after.skills == ["induced_order_query"]


def test_materialize_without_placeholders():
    register_induced_skill("order_query", QUERY_TEMPLATE, "induced_order_query")
    skill = skill_for_subtask(order_query_task())
    assert skill is not None
    assert skill.name == "induced_order_query"
    assert len(skill.steps) == 1
    assert skill.steps[0].name == "我的订单"
    assert skill.steps[0].role == "link"
    # unregistered operation stays an explicit gap
    clear_induced_skills()
    assert skill_for_subtask(order_query_task()) is None


# ---------------------------------------------------------------------------
# real HTTP: /orders page + header entries (no browser)
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


def test_site_orders_page_real_http():
    from step_rl.edge.site import LocalShopServer

    server = LocalShopServer().start()
    opener = _opener()
    base = server.base_url
    try:
        v1_home = _get(opener, base, "/")
        assert "我的订单" in v1_home[1] and "nav-orders" in v1_home[1]

        # empty state
        empty = _get(opener, base, "/orders")
        assert empty[0] == 200 and "暂无订单" in empty[1]

        # real order via the server API
        assert _get(opener, base, "/api/cart/set?pid=p3&qty=2")[0] == 200
        assert (
            _post(
                opener,
                base,
                "/place-order",
                b"name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
                b"&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
                b"%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7",
            )
            == 200
        )
        state = json.loads(_get(opener, base, "/api/state")[1])
        order_id = state["orders"][-1]["id"]
        listing = _get(opener, base, "/orders")
        assert listing[0] == 200
        assert order_id in listing[1] and "有效" in listing[1]

        # real cancel flips the rendered status
        assert _get(opener, base, f"/cancel/{order_id}")[0] == 200
        listing2 = _get(opener, base, "/orders")
        assert "已取消" in listing2[1]

        # the legacy single-order page keeps working
        single = _get(opener, base, f"/order/{order_id}")
        assert single[0] == 200 and order_id in single[1]
    finally:
        server.stop()

    server2 = LocalShopServer(layout="v2").start()
    opener2 = _opener()
    try:
        v2_home = _get(opener2, server2.base_url, "/")
        assert "aria-label='我的订单'" in v2_home[1]
    finally:
        server2.stop()


# ---------------------------------------------------------------------------
# real browser (Playwright + system Edge)
# ---------------------------------------------------------------------------


def test_real_browser_order_query_skill():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.runtime import run_skill_hierarchy
    from step_rl.edge.site import LocalShopServer

    register_induced_skill("order_query", QUERY_TEMPLATE, "induced_order_query")

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            await env.start()
            page = env._page
            base = server.base_url
            # seed a real order in the browser session
            await page.goto(base + "/api/cart/set?pid=p3&qty=2")
            await page.evaluate(
                "() => fetch('/place-order', {"
                "method: 'POST',"
                "headers: {'Content-Type': 'application/x-www-form-urlencoded'},"
                "body: 'name=%E5%88%98%E6%98%9F%E8%A8%80%E5%85%88%E7%94%9F"
                "&address=%E6%B7%B1%E5%9C%B3%E5%B8%82%E9%BE%99%E5%B1%B1%E5%8C%BA"
                "%E5%9D%82%E7%94%B0%E8%B7%AF1%E5%8F%B7'})"
            )
            # back to a real HTML page (the API responses above carry no DOM)
            await page.goto(base + "/")
            task = order_query_task()
            rollout = await run_skill_hierarchy(
                env, task, None, None, fallback=False, reset=False
            )
            state = await env.get_state()
            progress = compute_progress(state, env.page_url_path, task)
            assert rollout.success and progress.success
            assert "/orders" in state["visited"]
            assert state["orders"][-1]["status"] == "active"
            assert state["cart"] == {}
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
    stat = get_skill_stat("induced_order_query")
    assert stat is not None
    assert stat.attempts == 1
    assert stat.successes == 1
    assert not stat.demoted
