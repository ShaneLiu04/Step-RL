"""AR027: cart-wide transactional transforms on the real shop."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.planner import fetch_catalog, plan_instruction
from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TaskSpec


def test_planner_parses_cart_transforms():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        cases = [
            ("把购物车里的所有商品数量都加倍", "double"),
            ("把购物车里的所有商品数量改成3", "set:3"),
            ("把购物车里的每件商品数量加1", "add:1"),
        ]
        for instruction, expected in cases:
            spec = plan_instruction(instruction, catalog)
            assert spec is not None
            assert spec.operation == "transform"
            assert spec.cart_transform == expected
            assert spec.targets == {}
            assert spec.start_path == "/cart"
        # A named product is a normal single-item update, not a cart transform.
        normal = plan_instruction("把购物车里的无线充电器数量改成3", catalog)
        assert normal is not None
        assert normal.cart_transform == ""
    finally:
        server.stop()


async def _run(instruction, seed, server_kwargs=None, enable_cart_transform=True):
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.runtime import run_task

    server = LocalShopServer(**(server_kwargs or {})).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        try:
            await env.start()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"browser unavailable: {exc}")
        task = TaskSpec(
            task_id="cart_transform",
            level=3,
            goal=instruction,
            search_query="",
            targets={},
            start_path="/cart",
            seed_cart=seed,
        )
        await env.reset(task)
        result = await run_task(
            env,
            instruction,
            None,
            None,
            enable_cart_transform=enable_cart_transform,
        )
        state = await env.get_state()
        return result, state
    finally:
        await env.close()
        server.stop()


def test_real_double_transform():
    result, state = asyncio.run(
        _run("把购物车里的所有商品数量都加倍", {"p3": 1, "p4": 2})
    )
    assert result["success"]
    assert state["cart"] == {"p3": 2, "p4": 4}
    assert result["attempts"][0]["mode"] == "cart_transform"
    assert result["steps"]


def test_real_set_transform():
    result, state = asyncio.run(
        _run("把购物车里的所有商品数量改成3", {"p3": 2, "p2": 1})
    )
    assert result["success"]
    assert state["cart"] == {"p3": 3, "p2": 3}


def test_real_add_transform():
    result, state = asyncio.run(_run("把购物车里的每件商品数量加1", {"p3": 1, "p4": 1}))
    assert result["success"]
    assert state["cart"] == {"p3": 2, "p4": 2}


def test_baseline_without_transform_is_explicit_gap():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍",
            {"p3": 1, "p4": 2},
            enable_cart_transform=False,
        )
    )
    assert not result["success"]
    assert result["spec"] is None
    assert result["fallback_required"]
    assert state["cart"] == {"p3": 1, "p4": 2}


def test_real_failure_rolls_back():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍",
            {"p3": 1, "p4": 1},
            {"fault_update_once": True, "fault_update_pid": "p4"},
        )
    )
    assert not result["success"]
    assert result["compensated"] == 1
    assert state["cart"] == {"p3": 1, "p4": 1}
