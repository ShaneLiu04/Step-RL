"""SiteAdapter contract and normalized observation types (AR029)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class Element:
    role: str = ""
    name: str = ""
    value: str = ""
    state: Dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    selector: str = ""
    tag: str = ""
    eid: str = ""


@dataclass
class Observation:
    url: str
    title: str
    page_type: str
    elements: List[Element] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)
    revision: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "page_type": self.page_type,
            "elements": [e.__dict__ for e in self.elements],
            "signals": self.signals,
            "revision": self.revision,
        }


@dataclass
class Action:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    ok: bool
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    terminal: bool = False


@dataclass
class Verification:
    success: bool
    progress: float = 0.0
    predicates: Dict[str, bool] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterCapabilities:
    read: bool = True
    cart: bool = False
    checkout_dry_run: bool = False
    submit_order: bool = False
    cancel_order: bool = False
    orders: bool = False
    promo: bool = False
    auth: bool = False


@dataclass
class AuthHooks:
    requires_manual: bool = False
    login_url: str = ""
    note: str = ""


class SiteAdapter(Protocol):
    name: str
    capabilities: AdapterCapabilities

    async def open_session(
        self,
        *,
        storage_state: Optional[str] = None,
        manual_login: bool = False,
    ) -> None: ...

    async def close(self) -> None: ...

    async def observe(self) -> Observation: ...

    async def execute(self, action: Action) -> ActionResult: ...

    async def catalog(self) -> List[Dict[str, Any]]: ...

    async def promos(self) -> List[Dict[str, Any]]: ...

    async def verify(self, spec: Any) -> Verification: ...

    async def order_status(self, order_id: str) -> Dict[str, Any]: ...

    def auth_hooks(self) -> AuthHooks: ...
