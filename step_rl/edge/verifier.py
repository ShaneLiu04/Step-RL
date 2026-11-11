"""Executable dense progress derived from real server state.

No model output is trusted here.  ``compute_progress`` only reads the
authoritative session state returned by ``/api/state`` and the current URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List
from urllib.parse import parse_qs, urlparse

from .site import PRODUCTS
from .tasks import TaskSpec


@dataclass(frozen=True)
class ProgressResult:
    progress: float
    success: bool
    satisfied: tuple[str, ...]
    missing: tuple[str, ...]
    total: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "progress": self.progress,
            "success": self.success,
            "satisfied": list(self.satisfied),
            "missing": list(self.missing),
            "total": self.total,
        }


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _visited(state: Dict, predicate: Callable[[str], bool]) -> bool:
    return any(predicate(url) for url in state.get("visited", []))


def _path_is(target: str) -> Callable[[str], bool]:
    def check(url: str) -> bool:
        return urlparse(url).path.rstrip("/") == target.rstrip("/")

    return check


def _predicates(task: TaskSpec) -> Dict[str, Callable[[Dict, str], bool]]:
    target_ids = task.product_ids()
    query_set = {_norm(task.search_query)}
    for pid in target_ids:
        product = PRODUCTS.get(pid)
        if product:
            query_set.update(_norm(k) for k in product.keywords)

    def search_done(state: Dict, url: str) -> bool:
        if _norm(state.get("query", "")) in query_set:
            return True
        for visited in state.get("visited", []):
            parsed = urlparse(visited)
            if parsed.path == "/search":
                q = _norm(parse_qs(parsed.query).get("q", [""])[0])
                if q in query_set:
                    return True
        return False

    def product_viewed(state: Dict, url: str) -> bool:
        return _visited(
            state,
            lambda u: urlparse(u).path.startswith("/product/")
            and urlparse(u).path.split("/")[-1] in target_ids,
        )

    def cart_contains(state: Dict, url: str) -> bool:
        cart = state.get("cart", {})
        order = state.get("order") or {}
        ordered = order.get("items", {}) if order else {}
        compare = (
            (lambda a, b: a == b) if task.exact_quantity else (lambda a, b: a >= b)
        )
        return all(
            compare(max(int(cart.get(pid, 0)), int(ordered.get(pid, 0))), qty)
            for pid, qty in task.targets.items()
        )

    def cart_quantity_exact(state: Dict, url: str) -> bool:
        cart = state.get("cart", {})
        return all(int(cart.get(pid, 0)) == qty for pid, qty in task.targets.items())

    def cart_without(state: Dict, url: str) -> bool:
        cart = state.get("cart", {})
        return all(int(cart.get(pid, 0)) == 0 for pid in task.targets)

    def cart_viewed(state: Dict, url: str) -> bool:
        return _visited(state, _path_is("/cart"))

    def checkout_viewed(state: Dict, url: str) -> bool:
        return _visited(state, _path_is("/checkout"))

    def name_filled(state: Dict, url: str) -> bool:
        return bool(str((state.get("form") or {}).get("name", "")).strip())

    def address_filled(state: Dict, url: str) -> bool:
        return bool(str((state.get("form") or {}).get("address", "")).strip())

    def orders_all_cancelled(state: Dict, url: str) -> bool:
        history = state.get("orders") or []
        return bool(history) and all(
            order.get("status") == "cancelled" for order in history
        )

    def orders_sequence_placed(state: Dict, url: str) -> bool:
        history = state.get("orders") or []
        available = list(range(len(history)))
        for expected in task.order_sequence:
            matched = None
            for index in available:
                order = history[index]
                if all(
                    int(order.get("items", {}).get(pid, 0)) == qty
                    for pid, qty in expected.items()
                ):
                    matched = index
                    break
            if matched is None:
                return False
            available.remove(matched)
        return True

    def order_placed(state: Dict, url: str) -> bool:
        order = state.get("order")
        if not order:
            return False
        items = order.get("items", {})
        compare = (
            (lambda a, b: a == b) if task.exact_quantity else (lambda a, b: a >= b)
        )
        return all(
            compare(int(items.get(pid, 0)), qty) for pid, qty in task.targets.items()
        )

    return {
        "search_done": search_done,
        "product_viewed": product_viewed,
        "cart_contains": cart_contains,
        "cart_quantity_exact": cart_quantity_exact,
        "cart_without": cart_without,
        "cart_viewed": cart_viewed,
        "checkout_viewed": checkout_viewed,
        "name_filled": name_filled,
        "address_filled": address_filled,
        "orders_all_cancelled": orders_all_cancelled,
        "orders_sequence_placed": orders_sequence_placed,
        "order_placed": order_placed,
    }


def compute_progress(state: Dict, url: str, task: TaskSpec) -> ProgressResult:
    predicates = _predicates(task)
    names: List[str] = task.predicate_names()
    satisfied = tuple(name for name in names if predicates[name](state, url))
    missing = tuple(name for name in names if name not in satisfied)
    total = len(names)
    progress = len(satisfied) / total if total else 1.0
    return ProgressResult(
        progress=progress,
        success=len(missing) == 0,
        satisfied=satisfied,
        missing=missing,
        total=total,
    )


def task_success(state: Dict, url: str, task: TaskSpec) -> bool:
    return compute_progress(state, url, task).success
