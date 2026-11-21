"""LocalShopServer reference adapter (golden regression, AR029)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..browser import BrowserEnv
from ..planner import fetch_catalog, fetch_promos
from ..site import LocalShopServer
from ..tasks import TaskSpec
from ..verifier import compute_progress
from .base import (
    Action,
    ActionResult,
    AdapterCapabilities,
    AuthHooks,
    Element,
    Observation,
    Verification,
)


def _page_type(url: str) -> str:
    if "/product/" in url:
        return "product"
    if "/search" in url:
        return "search"
    if "/cart" in url:
        return "cart"
    if "/checkout" in url:
        return "checkout"
    if "/orders" in url or "/order/" in url:
        return "orders"
    return "home" if url.rstrip("/") in ("", "/") else "page"


class LocalAdapter:
    """Adapter over the existing local shop; behavior must remain identical."""

    name = "local"
    capabilities = AdapterCapabilities(
        read=True,
        cart=True,
        checkout_dry_run=False,
        submit_order=True,
        cancel_order=True,
        orders=True,
        promo=True,
        auth=False,
    )

    def __init__(self, server: LocalShopServer, **browser_kwargs: Any) -> None:
        self.server = server
        self._browser_kwargs = browser_kwargs
        self.env: Optional[BrowserEnv] = None

    async def open_session(
        self,
        *,
        storage_state: Optional[str] = None,
        manual_login: bool = False,
    ) -> None:
        if self.env is None:
            self.env = BrowserEnv(self.server, **self._browser_kwargs)
        await self.env.start()

    async def close(self) -> None:
        if self.env is not None:
            await self.env.close()
            self.env = None

    def _require(self) -> BrowserEnv:
        if self.env is None:
            raise RuntimeError("adapter session not open")
        return self.env

    async def reset(self, task: TaskSpec) -> Observation:
        await self._require().reset(task)
        return await self.observe()

    async def observe(self) -> Observation:
        env = self._require()
        obs = await env.observe()
        elements = [
            Element(
                role=str(item.get("role", "")),
                name=str(item.get("accessible_name", "")),
                value=str(item.get("value", "")),
                visible=True,
                selector=str(item.get("selector", "")),
                tag=str(item.get("tag", "")),
                eid=str(item.get("eid", "")),
            )
            for item in obs.get("elements", [])
        ]
        return Observation(
            url=str(obs.get("url", "")),
            title=str(obs.get("title", "")),
            page_type=_page_type(str(obs.get("url", ""))),
            elements=elements,
            signals={"state": obs.get("state", {})},
            revision=str(env.page_url_path),
        )

    async def execute(self, action: Action) -> ActionResult:
        env = self._require()
        raw = {"action": action.name, "params": dict(action.params)}
        result = await env.execute(raw)
        return ActionResult(
            ok=bool(result.get("ok")),
            error=str(result.get("error", "")),
            data={k: v for k, v in result.items() if k not in ("ok", "error")},
            terminal=bool(result.get("terminal", False)),
        )

    async def catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "pid": item.pid,
                "name": item.name,
                "price": item.price,
                "stock": item.stock,
                "keywords": list(item.keywords),
            }
            for item in fetch_catalog(self.server.base_url)
        ]

    async def promos(self) -> List[Dict[str, Any]]:
        return [
            {
                "code": item.code,
                "label": item.label,
                "threshold": item.threshold,
                "discount": item.discount,
            }
            for item in fetch_promos(self.server.base_url)
        ]

    async def verify(self, spec: TaskSpec) -> Verification:
        env = self._require()
        state = await env.get_state()
        progress = compute_progress(state, env.page_url_path, spec)
        predicates = {
            name: name in progress.satisfied for name in spec.predicate_names()
        }
        return Verification(
            success=progress.success,
            progress=progress.progress,
            predicates=predicates,
            evidence={
                "state": state,
                "url": env.page_url_path,
                "missing": list(progress.missing),
            },
        )

    async def order_status(self, order_id: str) -> Dict[str, Any]:
        env = self._require()
        state = await env.get_state()
        for order in state.get("orders", []):
            if str(order.get("id")) == str(order_id):
                return order
        return {}

    def auth_hooks(self) -> AuthHooks:
        return AuthHooks(requires_manual=False)
