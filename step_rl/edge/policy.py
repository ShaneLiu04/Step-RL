"""Prompt construction, JSON action parsing and DOM-grounding repair."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

ACTIONS = {"click", "type", "goto", "scroll", "wait", "finish"}

SYSTEM = "你是网页操作代理。根据任务、当前页面元素和历史，选择下一步动作。" "只能输出一个 JSON 对象，不要输出解释或 markdown。"

PREDICATE_HINTS = {
    "search_done": "完成搜索",
    "product_viewed": "打开目标商品页",
    "cart_contains": "把目标商品加入购物车",
    "cart_viewed": "打开购物车",
    "checkout_viewed": "进入结算",
    "name_filled": "填写收货人",
    "address_filled": "填写地址",
    "order_placed": "提交订单",
}


def _fmt_element(element: Dict[str, Any]) -> str:
    parts = [f"- {element.get('selector', '')}", f"<{element.get('tag', '')}>"]
    if element.get("type"):
        parts.append(f"type={element['type']}")
    if element.get("text"):
        parts.append(f"text={element['text']}")
    if element.get("placeholder"):
        parts.append(f"placeholder={element['placeholder']}")
    if element.get("name"):
        parts.append(f"name={element['name']}")
    if element.get("value"):
        parts.append(f"value={element['value']}")
    return " ".join(parts)


def _fmt_cart(state: Dict[str, Any]) -> str:
    cart = state.get("cart") or {}
    if not cart:
        return "空"
    return ", ".join(f"{pid}×{qty}" for pid, qty in sorted(cart.items()))


def build_prompt(
    task_goal: str,
    observation: Dict[str, Any],
    history: Optional[List[str]] = None,
    max_elements: int = 10,
    progress: Optional[float] = None,
    missing: Optional[List[str]] = None,
    reference_action: Optional[Dict[str, Any]] = None,
) -> str:
    elements = observation.get("elements", [])[:max_elements]
    state = observation.get("state", {})
    history = history or []
    history_text = "\n".join(history[-3:]) if history else "无"
    progress_line = ""
    if progress is not None:
        hints = [PREDICATE_HINTS.get(m, m) for m in (missing or [])]
        missing_text = "、".join(hints) if hints else "无"
        progress_line = f"进度: {progress:.2f} | 未完成: {missing_text}\n"
    reference_line = ""
    if reference_action:
        reference_line = f"参考动作: {render_action(reference_action)}\n"
    return (
        f"{SYSTEM}\n\n"
        f"任务: {task_goal}\n"
        f"页面: {observation.get('url', '/')} | {observation.get('title', '')}\n"
        + progress_line
        + reference_line
        + "可交互元素:\n"
        + "\n".join(_fmt_element(e) for e in elements)
        + f"\n购物车: {_fmt_cart(state)}\n"
        f"历史:\n{history_text}\n\n"
        '动作格式: {"thought":"简短理由","action":"click|type|goto|scroll|wait|finish",'
        '"params":{...}}\n'
        '示例: {"thought":"点击搜索","action":"click","params":{"selector":"#search-btn"}}\n'
        "下一步 JSON:"
    )


def render_action(action: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "thought": str(action.get("thought", ""))[:120],
            "action": action.get("action", "wait"),
            "params": action.get("params", {}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : idx + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def parse_action(text: str) -> Dict[str, Any]:
    obj = _extract_json(text)
    if obj is None:
        return {"action": "wait", "params": {}, "parse_error": "no_json"}
    action = str(obj.get("action", "")).lower().strip()
    params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
    if action not in ACTIONS:
        return {"action": "wait", "params": {}, "parse_error": f"bad_action:{action}"}
    return {
        "thought": str(obj.get("thought", ""))[:120],
        "action": action,
        "params": params,
        "parse_error": "",
    }


def _candidate_element(element: Dict[str, Any], action: str) -> bool:
    tag = element.get("tag", "")
    typ = element.get("type", "")
    if action == "type":
        return tag in ("input", "textarea", "select") and typ not in (
            "submit",
            "button",
        )
    if action == "click":
        return tag in ("button", "a", "input") or element.get("role") == "button"
    return True


def _score(element: Dict[str, Any], hints: List[str]) -> float:
    haystack = " ".join(
        str(element.get(k, ""))
        for k in ("selector", "text", "placeholder", "name", "value")
    ).lower()
    best = 0.0
    for hint in hints:
        hint = hint.lower().strip()
        if not hint:
            continue
        if hint in haystack:
            best = max(best, 1.0)
        else:
            best = max(best, SequenceMatcher(None, hint, haystack).ratio() * 0.8)
    return best


def repair_action(
    action: Dict[str, Any],
    elements: List[Dict[str, Any]],
    threshold: float = 0.6,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Repair an invalid selector using the *real* DOM snapshot.

    Returns the (possibly rewritten) action and diagnostics.  A rewrite only
    happens when exactly one candidate is clearly the best match.
    """

    info = {"raw_invalid": False, "repaired": False, "reason": ""}
    if action.get("action") not in ("click", "type"):
        return action, info

    params = dict(action.get("params") or {})
    selector = str(params.get("selector", ""))
    available = {e.get("selector") for e in elements}
    if selector and selector in available:
        return action, info

    info["raw_invalid"] = True
    hints = [
        str(params.get(k, ""))
        for k in ("text", "placeholder", "label", "name", "target")
        if params.get(k)
    ]
    if not hints and selector:
        hints = [selector.lstrip("#.")]
    candidates = [
        (el, _score(el, hints))
        for el in elements
        if _candidate_element(el, action["action"])
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)
    best = None
    if candidates and candidates[0][1] >= threshold:
        best_score = candidates[0][1]
        runner_up = candidates[1][1] if len(candidates) > 1 else 0.0
        if runner_up >= threshold and (best_score - runner_up) < 0.05:
            info["reason"] = "ambiguous"
            return action, info
        best = candidates[0][0]

    if best is None:
        # Generic, task-agnostic fallback: if the action type has exactly one
        # unambiguous target on the real page, use it.  This lets the agent
        # recover from stale selectors without guessing among many elements.
        if action["action"] == "type":
            empty_inputs = [
                el
                for el in elements
                if el.get("tag") in ("input", "textarea")
                and el.get("type") not in ("submit", "button")
                and not str(el.get("value", "")).strip()
            ]
            if len(empty_inputs) == 1:
                best = empty_inputs[0]
            else:
                inputs = [
                    el
                    for el in elements
                    if el.get("tag") in ("input", "textarea")
                    and el.get("type") not in ("submit", "button")
                ]
                if len(inputs) == 1:
                    best = inputs[0]
        elif action["action"] == "click":
            buttons = [
                el
                for el in elements
                if el.get("tag") == "button" and el.get("type") != "button"
            ]
            if len(buttons) == 1:
                best = buttons[0]

    if best is None:
        info["reason"] = "no_confident_match"
        return action, info

    params["selector"] = best["selector"]
    repaired = dict(action)
    repaired["params"] = params
    info["repaired"] = True
    info["reason"] = f"match:{best['selector']}"
    return repaired, info
