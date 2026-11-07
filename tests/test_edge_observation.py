"""AR008 observation pruning tests."""

from __future__ import annotations

from step_rl.edge.observation import prune_elements
from step_rl.edge.tasks import TASK_BY_ID


def _el(eid, name, tag="button"):
    return {
        "eid": eid,
        "selector": f"[data-eid={eid}]",
        "role": "button" if tag == "button" else "link",
        "accessible_name": name,
        "text": name,
        "placeholder": "",
        "name": "",
        "tag": tag,
    }


def test_decoys_are_removed():
    elements = [
        _el("e1", "搜索"),
        _el("e2", "排序"),
        _el("e3", "筛选"),
        _el("e4", "购物车", tag="a"),
    ]
    kept = prune_elements(elements, TASK_BY_ID["ev_search_p3"], ["search_done"])
    assert [e["eid"] for e in kept] == ["e1", "e4"]


def test_needed_elements_are_retained():
    elements = [
        _el("e1", "数量"),
        _el("e2", "加入购物车"),
        _el("e3", "收藏"),
    ]
    kept = prune_elements(elements, TASK_BY_ID["ev_qty_p3"], ["cart_contains"])
    assert "e3" not in [e["eid"] for e in kept]
    assert {"e1", "e2"} <= {e["eid"] for e in kept}


def test_empty_and_no_decoy_cases():
    assert prune_elements([], TASK_BY_ID["ev_qty_p3"], ["cart_contains"]) == []
    elements = [_el("e1", "搜索")]
    assert prune_elements(elements, TASK_BY_ID["ev_search_p3"], []) == elements
