"""Skill memory retrieval, adaptation and leakage guards."""

from __future__ import annotations

from pathlib import Path

from step_rl.edge.policy import build_prompt
from step_rl.edge.skill_memory import SkillMemory, page_type
from step_rl.edge.tasks import TASK_BY_ID

MEMORY = (
    Path(__file__).resolve().parent.parent / "step_rl" / "edge" / "skill_memory.json"
)


def test_page_types():
    assert page_type("/search?q=usb") == "search"
    assert page_type("/product/p1") == "product"
    assert page_type("/cart") == "cart"
    assert page_type("/checkout") == "checkout"
    assert page_type("/order/abc") == "order"


def test_memory_retrieves_checkout_name_action():
    memory = SkillMemory.load(MEMORY)
    task = TASK_BY_ID["ev_checkout_p3"]
    state = {"cart": {"p3": 2}, "order": None, "form": {}}
    record = memory.retrieve(
        task, "/checkout", ["name_filled", "address_filled", "order_placed"], state
    )
    assert record is not None
    action = memory.resolve(record, task, state)
    assert action is not None
    assert action["action"] == "type"
    assert action["params"]["selector"] == "#name"


def test_memory_adapts_product_selector():
    memory = SkillMemory.load(MEMORY)
    task = TASK_BY_ID["ev_multi_p3p4"]
    state = {"cart": {"p3": 1}, "order": None, "form": {}}
    record = memory.retrieve(
        task,
        "/cart",
        [
            "cart_contains",
            "cart_viewed",
            "checkout_viewed",
            "name_filled",
            "address_filled",
            "order_placed",
        ],
        state,
    )
    assert record is not None
    action = memory.resolve(record, task, state)
    assert action is not None
    assert action["action"] == "goto"
    assert "search" in action["params"]["url"]
    assert "蓝牙" in action["params"]["url"]


def test_memory_has_no_eval_task_traces():
    text = MEMORY.read_text(encoding="utf-8")
    for token in ("ev_qty_p3", "ev_qty_p4", "ev_multi_p3p4", "ev_checkout_p3"):
        assert token not in text


def test_prompt_includes_reference_action():
    prompt = build_prompt(
        "任务",
        {"url": "/checkout", "title": "结算", "elements": [], "state": {}},
        progress=0.5,
        missing=["name_filled"],
        reference_action={"action": "type", "params": {"selector": "#name"}},
    )
    assert "参考动作" in prompt
    assert "#name" in prompt
