"""Action parsing and DOM grounding repair."""

from __future__ import annotations

from step_rl.edge.policy import build_prompt, parse_action, repair_action

SEARCH_ELEMENTS = [
    {"selector": "#q", "tag": "input", "type": "text", "value": ""},
    {"selector": "#search-btn", "tag": "button", "type": "submit", "text": "搜索"},
]

CHECKOUT_ELEMENTS = [
    {"selector": "#name", "tag": "input", "type": "text", "value": ""},
    {"selector": "#address", "tag": "input", "type": "text", "value": "SZ"},
    {"selector": "#place-order", "tag": "button", "type": "submit", "text": "提交订单"},
]


def test_parse_strict_json():
    action = parse_action(
        '{"thought":"go","action":"click","params":{"selector":"#a"}}'
    )
    assert action["action"] == "click"
    assert action["parse_error"] == ""


def test_parse_fenced_json():
    action = parse_action(
        '```json\n{"action":"type","params":{"selector":"#q","text":"x"}}\n```'
    )
    assert action["action"] == "type"


def test_parse_rejects_unknown_action():
    action = parse_action('{"action":"delete","params":{}}')
    assert action["action"] == "wait"
    assert action["parse_error"].startswith("bad_action")


def test_repair_keeps_valid_selector():
    action = {"action": "click", "params": {"selector": "#search-btn"}}
    repaired, info = repair_action(action, SEARCH_ELEMENTS)
    assert repaired["params"]["selector"] == "#search-btn"
    assert not info["raw_invalid"]


def test_repair_unique_empty_input():
    action = {"action": "type", "params": {"selector": "#stale", "text": "张三"}}
    repaired, info = repair_action(action, CHECKOUT_ELEMENTS)
    assert info["raw_invalid"] and info["repaired"]
    assert repaired["params"]["selector"] == "#name"


def test_repair_unique_button():
    action = {"action": "click", "params": {"selector": "#stale"}}
    repaired, info = repair_action(action, CHECKOUT_ELEMENTS)
    assert info["repaired"]
    assert repaired["params"]["selector"] == "#place-order"


def test_ambiguous_input_is_not_guessed():
    elements = [
        {"selector": "#a", "tag": "input", "type": "text", "value": ""},
        {"selector": "#b", "tag": "input", "type": "text", "value": ""},
    ]
    action = {"action": "type", "params": {"selector": "#stale", "text": "x"}}
    repaired, info = repair_action(action, elements)
    assert not info["repaired"]
    assert repaired["params"]["selector"] == "#stale"


def test_prompt_contains_verifier_hints():
    prompt = build_prompt(
        "任务",
        {
            "url": "/checkout",
            "title": "结算",
            "elements": CHECKOUT_ELEMENTS,
            "state": {},
        },
        progress=0.5,
        missing=["name_filled", "order_placed"],
    )
    assert "未完成" in prompt
    assert "填写收货人" in prompt
    assert "提交订单" in prompt
