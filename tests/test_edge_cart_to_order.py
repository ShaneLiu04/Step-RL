"""AR028: cart transform -> checkout -> promo as one real transaction."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.planner import fetch_catalog, fetch_promos, plan_instruction
from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TaskSpec


def test_planner_compiles_cart_to_order():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        promos = fetch_promos(server.base_url)
        instruction = "把购物车里的所有商品数量都加倍，并使用满400减50优惠结算"
        spec = plan_instruction(instruction, catalog, promos)
        assert spec is not None
        assert spec.cart_transform == "double"
        assert spec.require_checkout
        assert spec.require_promo
        assert spec.promo == "man400jian50"
        plain = plan_instruction(
            "把购物车里的所有商品数量都加倍，并结算", catalog, promos
        )
        assert plain is not None and plain.require_checkout
        assert not plain.require_promo
        # AR027-only ablation: transform still compiles, but ignores checkout.
        legacy = plan_instruction(
            instruction,
            catalog,
            promos,
            enable_compound=False,
        )
        assert legacy is not None
        assert legacy.cart_transform == "double"
        assert not legacy.require_checkout
    finally:
        server.stop()


async def _run(instruction, seed, server_kwargs=None, enable_compound=True):
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.runtime import run_task

    server = LocalShopServer(**(server_kwargs or {})).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
        task = TaskSpec(
            task_id="cart_to_order",
            level=5,
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
            enable_compound=enable_compound,
        )
        state = await env.get_state()
        return result, state
    finally:
        await env.close()
        server.stop()


def test_real_transform_then_checkout():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍，并结算",
            {"p3": 1, "p4": 1},
        )
    )
    assert result["success"]
    assert state["order"] is not None
    assert state["order"]["items"] == {"p3": 2, "p4": 2}
    assert not (state["order"].get("promo") or {}).get("applied")


def test_real_transform_checkout_with_promo():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍，并使用满400减50优惠结算",
            {"p3": 1, "p4": 1},
        )
    )
    assert result["success"]
    order = state["order"]
    assert order is not None
    assert order["items"] == {"p3": 2, "p4": 2}
    assert order["promo"]["applied"]
    assert order["paid"] == order["total"] - 50


def test_promo_preflight_fails_before_actions():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍，并使用满2000减150优惠结算",
            {"p3": 1},
        )
    )
    assert not result["success"]
    assert result.get("preflight")
    assert state["cart"] == {"p3": 1}
    assert state["order"] is None


def test_baseline_ignores_checkout():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍，并结算",
            {"p3": 1, "p4": 1},
            enable_compound=False,
        )
    )
    # AR027 path transforms the cart but never places an order.
    assert state["cart"] == {"p3": 2, "p4": 2}
    assert state["order"] is None
    assert not result["success"] or state["order"] is None


def test_order_failure_rolls_back_cart():
    result, state = asyncio.run(
        _run(
            "把购物车里的所有商品数量都加倍，并结算",
            {"p3": 1, "p4": 1},
            {"fault_order_once": True},
        )
    )
    assert not result["success"]
    assert state["order"] is None
    assert state["cart"] == {"p3": 1, "p4": 1}
