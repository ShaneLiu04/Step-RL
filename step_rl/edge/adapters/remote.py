"""Generic read-only remote-site adapter (AR030).

Concrete sites (Taobao/Amazon) only supply URLs/host rules.  No login bypass,
no cart mutation, no order/payment.
"""

from __future__ import annotations

import re
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
from .session import BrowserSession

AMOUNT_RE = re.compile(r"(?:¥|￥|\$|€|£)\s*([0-9]+(?:[.,][0-9]+)?)")
BLOCK_WORDS = (
    "验证码",
    "captcha",
    "robot check",
    "异常流量",
    "安全验证",
    "访问过于频繁",
    "访问频繁",
    "无法搜索",
    "稍后再试",
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


class RemoteReadOnlyAdapter(BrowserSession):
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
        super().__init__(
            site_name=site_name,
            evidence=evidence,
            headless=headless,
            min_action_interval=min_action_interval,
            max_pages=max_pages,
        )
        self.search_template = search_template
        self.login_hosts = login_hosts
        self.item_hosts = item_hosts
        self.current_text = ""

    def search_url(self, query: str) -> str:
        return self.search_template.format(query=quote(query))

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
        page_type = (
            "login"
            if any(h in host for h in self.login_hosts)
            else ("product" if any(h in host for h in self.item_hosts) else "page")
        )
        title = await page.title()
        reason = blocked_reason(url, title, text)
        return Observation(
            url=url,
            title=title,
            page_type=page_type,
            elements=elements,
            signals={
                "blocked": reason,
                "amount": parse_amount(text),
                "text": text[:500],
            },
            revision=str(id(raw)),
        )

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
