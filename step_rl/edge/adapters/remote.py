"""Generic read-only remote-site adapter (AR030).

Concrete sites (Taobao/Amazon) only supply URLs/host rules.  No login bypass,
no cart mutation, no order/payment.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from ..browser import _OBSERVE_JS
from .base import (
    Action,
    ActionResult,
    AdapterCapabilities,
    AuthHooks,
    Element,
    Observation,
    Verification,
)
from .evidence import EvidenceWriter

AMOUNT_RE = re.compile(r"(?:¥|￥|\$|€|£)\s*([0-9]+(?:[.,][0-9]+)?)")
BLOCK_WORDS = (
    "验证码",
    "captcha",
    "robot check",
    "异常流量",
    "安全验证",
    "访问过于频繁",
)
LOGIN_TITLES = ("sign in", "sign-in", "登录", "log in", "login")


def parse_amount(text: str) -> Optional[float]:
    matches = AMOUNT_RE.findall(text.replace(",", ""))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(" ", ""))
    except ValueError:
        return None


def blocked_reason(url: str, title: str, text: str) -> str:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    lowered = (title + " " + text).lower()
    if any(word.lower() in lowered for word in BLOCK_WORDS):
        return "captcha_or_risk_control"
    if (
        "login" in host
        or "passport" in host
        or "signin" in host
        or "/ap/signin" in path
        or title.strip().lower() in LOGIN_TITLES
    ):
        return "login_required"
    return ""


class RemoteReadOnlyAdapter:
    name = "remote"
    capabilities = AdapterCapabilities(read=True)

    def __init__(
        self,
        *,
        site_name: str,
        search_template: str,
        login_hosts: tuple[str, ...] = (),
        item_hosts: tuple[str, ...] = (),
        evidence: Optional[EvidenceWriter] = None,
        headless: bool = True,
        min_action_interval: float = 5.0,
        max_pages: int = 20,
    ) -> None:
        self.name = site_name
        self.search_template = search_template
        self.login_hosts = login_hosts
        self.item_hosts = item_hosts
        self.evidence = evidence
        self.headless = headless
        self.min_action_interval = min_action_interval
        self.max_pages = max_pages
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.pages_loaded = 0
        self._last_action = 0.0
        self.current_text = ""

    def search_url(self, query: str) -> str:
        return self.search_template.format(query=quote(query))

    async def open_session(
        self,
        *,
        storage_state: Optional[str] = None,
        manual_login: bool = False,
    ) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kwargs: Dict[str, Any] = {"headless": self.headless}
        executable = os.environ.get("STEP_RL_BROWSER_PATH")
        if executable:
            launch_kwargs["executable_path"] = executable
        else:
            launch_kwargs["channel"] = "msedge"
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        context_kwargs: Dict[str, Any] = {"viewport": {"width": 1280, "height": 900}}
        if storage_state and Path(storage_state).exists():
            context_kwargs["storage_state"] = storage_state
        self._context = await self._browser.new_context(**context_kwargs)
        self.page = await self._context.new_page()
        self.page.set_default_timeout(15000)
        self._last_action = time.monotonic()

    async def close(self) -> None:
        for obj in (self._context, self._browser):
            try:
                if obj:
                    await obj.close()
            except Exception:
                pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

    def _require(self):
        if self.page is None:
            raise RuntimeError("session not open")
        return self.page

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_action
        if elapsed < self.min_action_interval:
            time.sleep(self.min_action_interval - elapsed)
        self._last_action = time.monotonic()

    def _count_page(self) -> None:
        if self.pages_loaded >= self.max_pages:
            raise RuntimeError(f"page budget exceeded: {self.pages_loaded}")
        self.pages_loaded += 1

    async def goto(self, url: str) -> None:
        self._require()
        self._rate_limit()
        self._count_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

    async def search(self, query: str) -> Observation:
        await self.goto(self.search_url(query))
        return await self.observe()

    async def open_product(self, url: str) -> Observation:
        await self.goto(url)
        return await self.observe()

    async def observe(self) -> Observation:
        page = self._require()
        raw = await page.evaluate(_OBSERVE_JS)
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
            for item in (raw.get("elements", []) if isinstance(raw, dict) else [])
        ]
        try:
            text = (await page.inner_text("body"))[:4000]
        except Exception:
            text = ""
        self.current_text = text
        url = page.url
        host = urlparse(url).netloc.lower()
        page_type = "login" if any(h in host for h in self.login_hosts) else (
            "product" if any(h in host for h in self.item_hosts) else "page"
        )
        reason = blocked_reason(url, await page.title(), text)
        return Observation(
            url=url,
            title=await page.title(),
            page_type=page_type,
            elements=elements,
            signals={
                "blocked": reason,
                "amount": parse_amount(text),
                "text": text[:500],
            },
            revision=str(id(raw)),
        )

    async def capture(self, name: str) -> Dict[str, str]:
        page = self._require()
        result = {}
        if self.evidence is not None:
            try:
                result["screenshot"] = str(
                    self.evidence.screenshot(await page.screenshot(), name)
                )
            except Exception:
                pass
            try:
                result["html"] = str(self.evidence.html(await page.content(), name))
            except Exception:
                pass
        return result

    async def save_storage_state(self, path: str) -> None:
        if self._context is None:
            raise RuntimeError("session not open")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(target))

    async def execute(self, action: Action) -> ActionResult:
        return ActionResult(False, "read-only adapter: execute disabled")

    async def catalog(self) -> List[Dict[str, Any]]:
        return []

    async def promos(self) -> List[Dict[str, Any]]:
        return []

    async def verify(self, spec: Any = None) -> Verification:
        obs = await self.observe()
        blocked = str(obs.signals.get("blocked", ""))
        return Verification(
            success=not blocked and bool(obs.title),
            progress=1.0 if not blocked else 0.0,
            predicates={
                "page_loaded": bool(obs.title),
                "not_blocked": not blocked,
            },
            evidence={"url": obs.url, "title": obs.title, "blocked": blocked},
        )

    async def order_status(self, order_id: str) -> Dict[str, Any]:
        return {"found": False, "reason": "read-only adapter"}

    def auth_hooks(self) -> AuthHooks:
        return AuthHooks(
            requires_manual=True,
            login_url="https://login.taobao.com/",
            note="AR030 read-only: login/captcha is manual only",
        )
