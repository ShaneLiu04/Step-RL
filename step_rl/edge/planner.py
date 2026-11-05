"""Constraint-aware task planning from natural-language instructions.

The planner reads the *live* catalog (price, stock) from the running shop and
compiles an instruction into a verifier-compatible ``TaskSpec``.  It is a
deterministic constraint solver, not a language-model guess.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

from .tasks import TaskSpec

_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_QTY_RE = re.compile(r"(\d+|[一二两三四五六七八九十]+)\s*(?:件|个|台|条|部)")
_BUDGET_RE = re.compile(r"(?:预算|不超过|以内|最多)\s*(\d+)|(\d+)\s*元(?:以内|以下)?")
_SPLIT_RE = re.compile(r"[，,；;。]|和|并|然后|再")


@dataclass(frozen=True)
class CatalogItem:
    pid: str
    name: str
    price: int
    stock: int
    keywords: tuple[str, ...]


def fetch_catalog(base_url: str) -> List[CatalogItem]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/api/products") as response:
        data = json.loads(response.read().decode("utf-8"))
    return [
        CatalogItem(
            pid=item["pid"],
            name=item["name"],
            price=int(item["price"]),
            stock=int(item.get("stock", 0)),
            keywords=tuple(item.get("keywords", ())),
        )
        for item in data
    ]


def _num(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token, 1)


def _qty_before(text: str, index: int) -> int:
    window = text[max(0, index - 12) : index]
    matches = list(_QTY_RE.finditer(window))
    if matches:
        return _num(matches[-1].group(1))
    return 1


def _mentions(instruction: str, catalog: List[CatalogItem]) -> List[tuple[str, int]]:
    """Return product mentions in textual order, with quantities."""

    found: List[tuple[int, str, int]] = []
    clauses = _SPLIT_RE.split(instruction)
    offset = 0
    for clause in clauses:
        if not clause:
            offset += 1
            continue
        candidates = []
        for item in catalog:
            needles = [item.name, *item.keywords]
            best = 0
            for needle in needles:
                if len(needle) >= 2 and needle.lower() in clause.lower():
                    best = max(best, len(needle))
            if best:
                candidates.append((best, item))
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        if candidates:
            _, item = candidates[0]
            idx = clause.lower().find(item.name.lower())
            if idx < 0:
                for needle in item.keywords:
                    idx = clause.lower().find(needle.lower())
                    if idx >= 0:
                        break
            qty = _qty_before(clause, max(0, idx))
            found.append((offset, item.pid, qty))
        offset += len(clause) + 1
    # de-duplicate by pid, keep the first textual occurrence
    seen = set()
    result: List[tuple[str, int]] = []
    for _, pid, qty in sorted(found):
        if pid in seen:
            continue
        seen.add(pid)
        result.append((pid, qty))
    return result


def _budget(instruction: str) -> Optional[int]:
    match = _BUDGET_RE.search(instruction)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _task_from_targets(
    instruction: str,
    catalog: List[CatalogItem],
    targets: Dict[str, int],
) -> Optional[TaskSpec]:
    if not targets:
        return None
    first = catalog[0]
    for item in catalog:
        if item.pid in targets:
            first = item
            break
    checkout = any(word in instruction for word in ("结算", "下单", "购买"))
    multi = len(targets) > 1
    qty_large = any(qty >= 2 for qty in targets.values())
    if checkout:
        level = 5 if multi else 4
    else:
        level = 3 if qty_large else 2
    return TaskSpec(
        task_id="planned",
        level=level,
        goal=instruction,
        search_query=first.keywords[0] if first.keywords else first.name,
        targets=targets,
        require_checkout=checkout,
        split="planned",
    )


def plan_instruction(
    instruction: str, catalog: List[CatalogItem]
) -> Optional[TaskSpec]:
    """Compile a constrained instruction into a TaskSpec."""

    budget = _budget(instruction)
    mentions = _mentions(instruction, catalog)
    by_pid = {item.pid: item for item in catalog}

    # Substitution: "A 缺货则 B".
    if "缺货" in instruction and len(mentions) >= 2:
        in_stock = [pid for pid, _ in mentions if by_pid[pid].stock > 0]
        if in_stock:
            return _task_from_targets(instruction, catalog, {in_stock[0]: 1})
        return None

    if mentions:
        targets: Dict[str, int] = {}
        for pid, qty in mentions:
            if by_pid[pid].stock >= qty:
                targets[pid] = targets.get(pid, 0) + qty
        if budget is not None:
            total = sum(by_pid[pid].price * qty for pid, qty in targets.items())
            if total > budget:
                # drop the most expensive line until it fits or is empty
                for pid in sorted(
                    targets, key=lambda p: by_pid[p].price * targets[p], reverse=True
                ):
                    if total <= budget:
                        break
                    total -= by_pid[pid].price * targets[pid]
                    targets.pop(pid, None)
        return _task_from_targets(instruction, catalog, targets)

    # No explicit product: choose from all in-stock items.
    candidates = [item for item in catalog if item.stock > 0]
    if budget is not None:
        candidates = [item for item in candidates if item.price <= budget]
    if not candidates:
        return None
    if "最便宜" in instruction or "最低" in instruction:
        item = min(candidates, key=lambda i: i.price)
    elif "最贵" in instruction or "最高" in instruction:
        item = max(candidates, key=lambda i: i.price)
    else:
        item = candidates[0]
    return _task_from_targets(instruction, catalog, {item.pid: 1})


def naive_plan(instruction: str, catalog: List[CatalogItem]) -> Optional[TaskSpec]:
    """Keyword-only baseline: first mentioned product, quantity 1."""

    for item in catalog:
        if item.name in instruction or any(
            len(k) >= 2 and k in instruction for k in item.keywords
        ):
            return _task_from_targets(instruction, catalog, {item.pid: 1})
    return None
