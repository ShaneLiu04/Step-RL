"""Skill memory: state -> action templates extracted from real expert runs.

The memory is intentionally small and auditable.  It is built only from
successful trajectories on *training* tasks (p1/p2), never from held-out
evaluation tasks.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .site import PRODUCTS
from .tasks import TaskSpec

NAME = "刘星言"
ADDRESS = "深圳市龙岗区坂田街道"

_PRODUCT_RE = re.compile(r"product-(p\d+)")
_ADD_RE = re.compile(r"^/add/(p\d+)\?qty=(\d+)$")
_SEARCH_RE = re.compile(r"^/search\?q=(.*)$")


def page_type(url: str) -> str:
    path = urlparse(url).path or "/"
    if path == "/" or path == "/search":
        return "search"
    if path.startswith("/product/"):
        return "product"
    if path == "/cart":
        return "cart"
    if path == "/checkout":
        return "checkout"
    if path.startswith("/order/"):
        return "order"
    return "other"


@dataclass
class MemoryRecord:
    level: int
    require_checkout: bool
    page_type: str
    missing: List[str]
    action: Dict[str, Any]
    delta_phi: float
    target_pid: Optional[str] = None
    hits: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not data.get("extra"):
            data.pop("extra", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        return cls(
            level=int(data["level"]),
            require_checkout=bool(data["require_checkout"]),
            page_type=str(data["page_type"]),
            missing=list(data["missing"]),
            action=dict(data["action"]),
            delta_phi=float(data.get("delta_phi", 0.0)),
            target_pid=data.get("target_pid"),
            hits=int(data.get("hits", 1)),
            extra=dict(data.get("extra", {})),
        )


def compact_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """Replace task-specific values with placeholders."""

    name = action.get("action", "wait")
    params = dict(action.get("params") or {})
    selector = str(params.get("selector", ""))
    compressed = dict(action)
    compressed["params"] = params

    if name == "click":
        match = _PRODUCT_RE.search(selector)
        if match:
            params["selector"] = "#product-@PID@"
    elif name == "type":
        if selector == "#q":
            params["text"] = "@QUERY@"
        elif selector == "#qty":
            params["text"] = "@QTY@"
        elif selector == "#name":
            params["text"] = "@NAME@"
        elif selector == "#address":
            params["text"] = "@ADDRESS@"
    elif name == "goto":
        url = str(params.get("url", ""))
        if _SEARCH_RE.match(url):
            params["url"] = "/search?q=@QUERY@"
        elif _ADD_RE.match(url):
            pid, qty = _ADD_RE.match(url).groups()  # type: ignore[union-attr]
            params["url"] = "/add/@PID@?qty=@QTY@"
            compressed["target_pid"] = pid
        elif url.startswith("/product/p"):
            params["url"] = "/product/@PID@"
    return compressed


def target_pid_of(action: Dict[str, Any]) -> Optional[str]:
    params = action.get("params") or {}
    for value in (params.get("selector", ""), params.get("url", "")):
        match = _PRODUCT_RE.search(str(value)) or _ADD_RE.match(str(value))
        if match:
            return match.group(1)
    return None


class SkillMemory:
    def __init__(self, records: List[MemoryRecord]) -> None:
        self.records = records

    @classmethod
    def load(cls, path: str | Path) -> "SkillMemory":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([MemoryRecord.from_dict(item) for item in data])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                [record.to_dict() for record in self.records],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- retrieval --------------------------------------------------------
    def retrieve(
        self,
        task: TaskSpec,
        url: str,
        missing: List[str],
        state: Dict[str, Any],
    ) -> Optional[MemoryRecord]:
        current_type = page_type(url)
        current_missing = set(missing)
        best: Optional[MemoryRecord] = None
        best_score = -1.0
        for record in self.records:
            if record.page_type != current_type:
                continue
            if record.require_checkout != task.require_checkout:
                continue
            record_missing = set(record.missing)
            union = current_missing | record_missing
            inter = current_missing & record_missing
            if not inter:
                continue
            jaccard = len(inter) / max(1, len(union))
            score = (
                3.0 * jaccard
                + 1.0
                + 0.5 * (1.0 / (1 + abs(record.level - task.level)))
                + 0.2 * record.delta_phi
            )
            # A suggested action must still be applicable to a pending target.
            if record.target_pid and not self._pending_pid(task, state):
                continue
            if score > best_score:
                best_score = score
                best = record
        return best

    def resolve(
        self, record: MemoryRecord, task: TaskSpec, state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        pid = self._select_pid(record, task, state)
        if pid is None:
            return None
        action = json.loads(json.dumps(record.action))
        params = action.setdefault("params", {})
        product = PRODUCTS.get(pid)
        query = product.keywords[0] if product else task.search_query
        current = self._current_qty(pid, state)
        required = int(task.targets.get(pid, 1))
        remaining = max(1, required - current)

        for key, value in list(params.items()):
            if not isinstance(value, str):
                continue
            value = value.replace("@PID@", pid)
            value = value.replace("@QUERY@", query)
            value = value.replace("@QTY@", str(remaining))
            value = value.replace("@NAME@", NAME)
            value = value.replace("@ADDRESS@", ADDRESS)
            params[key] = value
        return action

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _current_qty(pid: str, state: Dict[str, Any]) -> int:
        cart = state.get("cart") or {}
        order = state.get("order") or {}
        ordered = order.get("items") or {}
        return max(int(cart.get(pid, 0)), int(ordered.get(pid, 0)))

    def _pending_pid(self, task: TaskSpec, state: Dict[str, Any]) -> Optional[str]:
        for pid, qty in task.targets.items():
            if self._current_qty(pid, state) < qty:
                return pid
        return None

    def _select_pid(
        self, record: MemoryRecord, task: TaskSpec, state: Dict[str, Any]
    ) -> Optional[str]:
        pending = self._pending_pid(task, state)
        if record.target_pid:
            return pending or record.target_pid
        return pending or next(iter(task.targets), None)
