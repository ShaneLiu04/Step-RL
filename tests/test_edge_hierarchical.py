"""Hierarchical decomposition and adapter routing tests."""

from __future__ import annotations

from step_rl.edge.hierarchical import adapter_for_subtask, decompose_task
from step_rl.edge.tasks import TASK_BY_ID


def test_single_item_checkout_decomposition():
    subtasks = decompose_task(TASK_BY_ID["ev_checkout_p4"])
    assert len(subtasks) == 2
    assert [s.task_id.split("__")[-1] for s in subtasks] == ["add_p4", "checkout"]
    assert subtasks[0].targets == {"p4": 1}
    assert subtasks[0].require_checkout is False
    assert subtasks[1].require_checkout is True


def test_quantity_checkout_decomposition():
    subtasks = decompose_task(TASK_BY_ID["ev_checkout_p3"])
    assert len(subtasks) == 2
    assert subtasks[0].targets == {"p3": 2}
    assert "数量 2" in subtasks[0].goal


def test_multi_item_decomposition_order():
    subtasks = decompose_task(TASK_BY_ID["ev_multi_p3p4"])
    assert len(subtasks) == 3
    assert subtasks[0].targets == {"p3": 1}
    assert subtasks[1].targets == {"p4": 2}
    assert subtasks[2].require_checkout is True


def test_non_checkout_task_is_unchanged():
    task = TASK_BY_ID["ev_qty_p4"]
    assert decompose_task(task) == [task]


def test_adapter_routing():
    subtasks = decompose_task(TASK_BY_ID["ev_multi_p3p4"])
    assert adapter_for_subtask(subtasks[0]) == "base"
    assert adapter_for_subtask(subtasks[1]) == "quantity"
    assert adapter_for_subtask(subtasks[2]) == "checkout"
