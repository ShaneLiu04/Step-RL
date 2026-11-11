"""AR019 failure-driven skill induction tests."""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.request

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.capability import check_capability
from step_rl.edge.planner import fetch_catalog, plan_instruction
from step_rl.edge.site import LocalShopServer
from step_rl.edge.skill_induction import RecordedStep, induce_skill
from step_rl.edge.skill_library import (
    clear_induced_skills,
    induced_operations,
    load_induced_skills,
    register_induced_skill,
    run_skill_hierarchy,
    save_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_induced_skills()
    yield
    clear_induced_skills()


def _opener(server):
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _remove_task(pid: str = "p3", seed: int = 2) -> TaskSpec:
    return TaskSpec(
        task_id="rm",
        level=2,
        goal="把购物车中的商品移除",
        search_query="x",
        targets={pid: 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: seed},
    )


def test_remove_route_real_http():
    server = LocalShopServer().start()
    try:
        opener = _opener(server)
        opener.open(server.base_url + "/api/cart/set?pid=p3&qty=2").read()
        opener.open(server.base_url + "/api/cart/set?pid=p4&qty=1").read()
        opener.open(server.base_url + "/remove/p3").read()
        state = json.loads(
            opener.open(server.base_url + "/api/state").read().decode("utf-8")
        )
        assert state["cart"] == {"p4": 1}
    finally:
        server.stop()


def test_cart_without_predicate():
    task = _remove_task()
    assert compute_progress({"cart": {"p4": 2}}, "/cart", task).success
    assert not compute_progress({"cart": {"p3": 1}}, "/cart", task).success


def test_planner_parses_remove_instruction():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = plan_instruction("把购物车中的无线充电器移除", catalog)
        assert spec is not None
        assert spec.operation == "remove"
        assert spec.predicates == ["cart_without"]
        assert spec.targets == {"p3": 0}
        assert spec.start_path == "/cart"
        assert spec.seed_cart == {"p3": 1}
    finally:
        server.stop()


def test_capability_gap_before_registration():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        cap = check_capability("把购物车中的无线充电器移除", catalog)
        assert not cap.covered
        assert cap.reason.startswith("no_skill")
        assert skill_for_subtask(_remove_task()) is None
    finally:
        server.stop()


def test_induce_skill_generalises_product_and_qty():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task()
        records = [
            RecordedStep(kind="goto", url="/cart"),
            RecordedStep(
                kind="click", role="button", name="移除 无线充电器"
            ),
        ]
        template = induce_skill(task, records, catalog)
        assert template["steps"][0] == {"kind": "goto", "url": "/cart"}
        click = template["steps"][1]
        assert click["name"] == "移除 {product}"
        assert click["role"] == "button"
    finally:
        server.stop()


def test_register_and_capability_covered(tmp_path):
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        template = induce_skill(
            _remove_task(),
            [RecordedStep(kind="click", role="button", name="移除 无线充电器")],
            catalog,
        )
        register_induced_skill("remove", template["steps"], template["name"])
        assert induced_operations() == ["remove"]
        skill = skill_for_subtask(_remove_task(pid="p4"))
        assert skill is not None
        assert skill.steps[0].name == "移除 蓝牙降噪耳机"

        cap = check_capability("把购物车中的无线充电器移除", catalog)
        assert cap.covered
        assert cap.skills == ["induced_remove"]

        path = tmp_path / "induced.json"
        save_induced_skills(str(path))
        clear_induced_skills()
        assert skill_for_subtask(_remove_task()) is None
        assert load_induced_skills(str(path)) == ["remove"]
        assert skill_for_subtask(_remove_task()) is not None
    finally:
        server.stop()


def test_induced_skill_real_browser():
    pytest.importorskip("playwright")

    task = _remove_task()
    register_induced_skill(
        "remove",
        [{"kind": "click", "role": "button", "name": "移除 {product}"}],
        "induced_remove",
    )

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
            assert rollout.success
            state = await env.get_state()
            assert state["cart"] == {}
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
