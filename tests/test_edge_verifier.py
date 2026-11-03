"""Verifier determinism and dense-progress invariants."""

from __future__ import annotations

from step_rl.edge.tasks import TASK_BY_ID
from step_rl.edge.verifier import compute_progress


def _state(**overrides):
    base = {
        "query": "",
        "cart": {},
        "form": {},
        "order": None,
        "visited": [],
    }
    base.update(overrides)
    return base


def test_progress_is_deterministic():
    task = TASK_BY_ID["ev_checkout_p4"]
    state = _state(
        query="蓝牙",
        cart={"p4": 1},
        visited=["/search?q=蓝牙", "/product/p4", "/cart", "/checkout"],
    )
    first = compute_progress(state, "/checkout", task)
    second = compute_progress(state, "/checkout", task)
    assert first == second
    assert 0 < first.progress < 1


def test_success_requires_order():
    task = TASK_BY_ID["ev_checkout_p4"]
    state = _state(
        query="蓝牙",
        cart={"p4": 1},
        form={"name": "A", "address": "B"},
        visited=["/search?q=蓝牙", "/product/p4", "/cart", "/checkout"],
    )
    assert not compute_progress(state, "/checkout", task).success
    state["order"] = {"id": "x", "items": {"p4": 1}}
    state["cart"] = {}
    assert compute_progress(state, "/order/x", task).success


def test_quantity_predicate():
    task = TASK_BY_ID["ev_qty_p3"]
    state = _state(query="无线", cart={"p3": 1}, visited=["/product/p3"])
    assert not compute_progress(state, "/cart", task).success
    state["cart"]["p3"] = 2
    assert compute_progress(state, "/cart", task).success


def test_missing_predicates_are_reported():
    task = TASK_BY_ID["ev_multi_p3p4"]
    result = compute_progress(_state(), "/", task)
    assert "search_done" in result.missing
    assert "order_placed" in result.missing
    assert result.progress == 0.0
