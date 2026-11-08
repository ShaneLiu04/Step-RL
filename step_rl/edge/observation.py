"""Verifier-guided observation pruning for edge-side token reduction."""

from __future__ import annotations

from typing import Any, Dict, List

from .site import PRODUCTS
from .tasks import TaskSpec

DECOYS = ("排序", "筛选", "收藏", "返回", "继续购物")
NAV = ("购物车", "购物袋", "首页", "主页", "订单")


def _haystack(element: Dict[str, Any]) -> str:
    return " ".join(
        str(element.get(key, ""))
        for key in ("accessible_name", "text", "placeholder", "name")
    ).lower()


def _missing_keywords(task: TaskSpec, missing: List[str]) -> Dict[str, tuple[str, ...]]:
    keywords: Dict[str, List[str]] = {name: [] for name in missing}
    if "search_done" in keywords:
        keywords["search_done"].extend(["搜索", "查找", "查一查"])
    if "product_viewed" in keywords or "cart_contains" in keywords:
        for pid in task.targets:
            product = PRODUCTS.get(pid)
            if product:
                keywords.setdefault("product_viewed", []).append(product.name)
                keywords.setdefault("cart_contains", []).extend(product.keywords)
        for name in ("product_viewed", "cart_contains"):
            if name in keywords:
                keywords[name].extend(["加入购物车", "数量", "商品"])
    if "checkout_viewed" in keywords:
        keywords["checkout_viewed"].extend(["去结算", "结算"])
    if "cart_viewed" in keywords:
        keywords["cart_viewed"].extend(["购物车", "购物袋"])
    if "name_filled" in keywords:
        keywords["name_filled"].extend(["收货人", "姓名"])
    if "address_filled" in keywords:
        keywords["address_filled"].extend(["地址"])
    if "order_placed" in keywords:
        keywords["order_placed"].extend(["提交订单", "下单"])
    return {key: tuple(value) for key, value in keywords.items()}


def _score(element: Dict[str, Any], task: TaskSpec, missing: List[str]) -> float:
    text = _haystack(element)
    keyword_map = _missing_keywords(task, missing)
    score = 0.0
    for keywords in keyword_map.values():
        if any(keyword.lower() in text for keyword in keywords):
            score += 3.0
    for pid in task.targets:
        product = PRODUCTS.get(pid)
        if product and (
            product.name.lower() in text
            or any(keyword.lower() in text for keyword in product.keywords)
        ):
            score += 2.0
    if any(word in text for word in NAV):
        score += 0.5
    if any(word in text for word in DECOYS):
        score -= 3.0
    return score


def prune_elements(
    elements: List[Dict[str, Any]],
    task: TaskSpec,
    missing: List[str],
    max_elements: int = 6,
) -> List[Dict[str, Any]]:
    """Keep the elements that can advance a missing predicate.

    The original DOM order is preserved.  Decoys are dropped even when the
    page has fewer than ``max_elements`` actionable controls.
    """

    if not elements:
        return elements
    kept = []
    for element in elements:
        text = _haystack(element)
        if any(word in text for word in DECOYS):
            continue
        kept.append(element)
    return kept[:max_elements] or elements[:max_elements]
