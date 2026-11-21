"""JD real-site adapter (AR029, dry-run by default).

All JD-specific selectors/URLs live here; core never imports this module.
Real browser = system Edge via Playwright.  No submit/payment is implemented.
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

SEARCH_URL = "https://search.jd.com/Search?keyword={query}&enc=utf-8"
ITEM_RE = re.compile(r"item\.jd\.com/(\d+)")
AMOUNT_RE = re.compile(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)")
ORDER_RE = re.compile(r"\b(\d{8,20})\b")
DANGEROUS = ("提交订单", "立即购买", "去支付", "支付", "确认支付")


def jd_search_url(query: str) -> str:
    return SEARCH_URL.format(query=quote(query))


def is_checkout_url(url: str) -> bool:
    return "trade.jd.com" in url or "checkout" in url.lower()


def extract_amount(text: str) -> Optional[float]:
    matches = AMOUNT_RE.findall(text.replace(",", ""))
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


class JDAdapter:
    name = "jd"
    capabilities = AdapterCapabilities(
        read=True,
        cart=True,
        checkout_dry_run=True,
        submit_order=False,
        cancel_order=False,
        orders=True,
        promo=True,
        auth=True,
    )

    def __init__(
        self,
        *,
        evidence: Optional[EvidenceWriter] = None,
        headless: bool = False,
        min_action_interval: float = 5.0,
        max_pages: int = 20,
        max_amount: float = 200.0,
        allow_submit: bool = False,
    ) -> None:
        self.evidence = evidence
        self.headless = headless
        self.min_action_interval = min_action_interval
        self.max_pages = max_pages
        self.max_amount = max_amount
        self.allow_submit = allow_submit
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.pages_loaded = 0
        self._last_action = 0.0
        self.current_text = ""

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
        if manual_login:
            await self.page.goto("https://www.jd.com/", wait_until="domcontentloaded")
            await self._settle()

    async def save_storage_state(self, path: str) -> None:
        if self._context is None:
            raise RuntimeError("JD session not open")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(target))

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
            raise RuntimeError("JD session not open")
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

    async def _settle(self) -> None:
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        # JD often redirects/refreshes after DOMContentLoaded (login/risk-control
        # interstitials).  Give navigation a moment, then observe with retries.
        await asyncio.sleep(1.8)

    async def _evaluate_observe(self):
        last_error = None
        for _ in range(4):
            try:
                return await self.page.evaluate(_OBSERVE_JS)
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if "execution context was destroyed" not in message and "navigation" not in message:
                    raise
                try:
                    await self.page.wait_for_load_state(
                        "domcontentloaded", timeout=8000
                    )
                except Exception:
                    pass
                await asyncio.sleep(1.5)
        raise RuntimeError(f"JD observation failed after navigation retries: {last_error}")

    async def goto(self, url: str) -> None:
        self._require()
        self._rate_limit()
        self._count_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self._settle()

    async def search(self, query: str) -> Observation:
        await self.goto(jd_search_url(query))
        obs = await self.observe()
        if obs.page_type == "login" or obs.signals.get("login_required"):
            raise RuntimeError(
                "JD login/captcha required: rerun with --manual-login and complete it manually"
            )
        if obs.signals.get("risk_control"):
            raise RuntimeError(
                "JD risk control: 访问频繁/无法搜索; pause and retry later with low frequency"
            )
        return obs

    async def open_product(self, url: str) -> Observation:
        await self.goto(url)
        return await self.observe()

    async def observe(self) -> Observation:
        page = self._require()
        raw = await self._evaluate_observe()
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
        if "passport" in host or "login" in host:
            page_type = "login"
        elif host.startswith("search."):
            page_type = "search"
        elif host.startswith("item."):
            page_type = "product"
        elif host.startswith("cart."):
            page_type = "cart"
        elif is_checkout_url(url):
            page_type = "checkout"
        elif host.startswith("order."):
            page_type = "orders"
        else:
            page_type = "page"
        title = await page.title()
        risk_control = any(
            word in text for word in ("访问频繁", "无法搜索", "稍后再试", "安全验证", "验证码")
        )
        signals = {
            "login_required": page_type == "login" or "请登录" in text,
            "risk_control": risk_control,
            "amount": extract_amount(text),
            "has_submit": any(word in text for word in DANGEROUS),
            "item_ids": ITEM_RE.findall(text),
        }
        return Observation(
            url=url,
            title=title,
            page_type=page_type,
            elements=elements,
            signals=signals,
            revision=str(id(raw)),
        )

    async def capture(self, name: str) -> Dict[str, str]:
        page = self._require()
        result = {}
        if self.evidence is not None:
            try:
                png = await page.screenshot(full_page=False)
                result["screenshot"] = str(self.evidence.screenshot(png, name))
            except Exception:
                pass
            try:
                html = await page.content()
                result["html"] = str(self.evidence.html(html, name))
            except Exception:
                pass
        return result

    async def execute(self, action: Action) -> ActionResult:
        page = self._require()
        if action.name in ("click",) and action.params.get("element"):
            eid = str(action.params["element"])
            locator = page.locator(f'[data-eid="{eid}"]')
            if await locator.count() != 1:
                return ActionResult(False, f"element not found: {eid}")
            try:
                text = (await locator.inner_text())[:80]
            except Exception:
                text = ""
            if any(word in text for word in DANGEROUS) and not self.allow_submit:
                return ActionResult(False, "blocked dangerous action in dry-run")
            self._rate_limit()
            await locator.click()
            await self._settle()
            return ActionResult(True)
        if action.name == "goto":
            await self.goto(str(action.params.get("url", "")))
            return ActionResult(True)
        return ActionResult(False, f"unsupported action: {action.name}")

    async def collect_buttons(self) -> List[str]:
        page = self._require()
        texts = await page.eval_on_selector_all(
            "button,a", "els => els.map(e => (e.innerText||'').trim()).filter(Boolean)"
        )
        return [str(text) for text in texts]

    async def add_to_cart(self, quantity: int = 1) -> Observation:
        page = self._require()
        self._rate_limit()
        locator = page.get_by_text(re.compile(r"加入购物车|加购"), exact=False)
        if await locator.count() == 0:
            raise RuntimeError("JD add-to-cart control not found (DOM changed or not logged in)")
        await locator.first.click()
        await self._settle()
        if quantity > 1:
            await self.set_cart_quantity(quantity)
        return await self.observe()

    async def read_cart(self) -> Dict[str, Any]:
        await self.goto("https://cart.jd.com/cart.action")
        obs = await self.observe()
        await self.capture("cart")
        return {
            "url": obs.url,
            "text": self.current_text[:2000],
            "contains_cart": "购物车" in obs.title or "cart" in obs.url,
            "signals": obs.signals,
        }

    async def set_cart_quantity(self, quantity: int) -> Observation:
        page = self._require()
        self._rate_limit()
        inputs = page.locator("input[type=text], input[type=number]")
        count = await inputs.count()
        if count == 0:
            raise RuntimeError("JD cart quantity input not found")
        # JD cart uses item rows; first visible quantity input is the first item.
        await inputs.first.fill(str(max(1, quantity)))
        await self._settle()
        return await self.observe()

    async def remove_from_cart(self) -> Observation:
        page = self._require()
        self._rate_limit()
        locator = page.get_by_text(re.compile(r"删除|移除"), exact=False)
        if await locator.count() == 0:
            raise RuntimeError("JD remove control not found")
        await locator.first.click()
        await self._settle()
        return await self.observe()

    async def open_checkout(self) -> Dict[str, Any]:
        page = self._require()
        self._rate_limit()
        locator = page.get_by_text(re.compile(r"去结算|结算"), exact=False)
        if await locator.count() == 0:
            raise RuntimeError("JD checkout control not found")
        await locator.first.click()
        await self._settle()
        obs = await self.observe()
        await self.capture("checkout")
        return {
            "url": obs.url,
            "text": self.current_text[:2000],
            "amount": obs.signals.get("amount"),
            "checkout_reached": is_checkout_url(obs.url),
            "has_submit": obs.signals.get("has_submit"),
        }

    async def read_orders(self) -> Dict[str, Any]:
        await self.goto("https://order.jd.com/center/list.action")
        obs = await self.observe()
        await self.capture("orders")
        return {
            "url": obs.url,
            "text": self.current_text[:3000],
            "order_ids": ORDER_RE.findall(self.current_text),
        }

    async def order_status(self, order_id: str) -> Dict[str, Any]:
        data = await self.read_orders()
        found = str(order_id) in data.get("text", "")
        return {
            "order_id": str(order_id),
            "found": found,
            "url": data.get("url"),
            "text": data.get("text", "")[:500],
        }

    async def verify_checkout_dryrun(self) -> Verification:
        obs = await self.observe()
        amount = obs.signals.get("amount")
        success = bool(is_checkout_url(obs.url) and amount is not None)
        if amount is not None and amount > self.max_amount:
            success = False
        return Verification(
            success=success,
            progress=1.0 if success else 0.0,
            predicates={
                "checkout_reached": is_checkout_url(obs.url),
                "amount_read": amount is not None,
                "within_amount_cap": amount is None or amount <= self.max_amount,
                "no_submit": not obs.signals.get("has_submit"),
            },
            evidence={
                "url": obs.url,
                "title": obs.title,
                "amount": amount,
                "signals": obs.signals,
            },
        )

    async def catalog(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("JD catalog is read from live search/product pages")

    async def promos(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("JD promo feasibility is adapter-specific")

    async def verify(self, spec: Any) -> Verification:
        return await self.verify_checkout_dryrun()

    def auth_hooks(self) -> AuthHooks:
        return AuthHooks(
            requires_manual=True,
            login_url="https://passport.jd.com/new/login.aspx",
            note="Login/captcha must be handled manually; never bypass.",
        )

    async def submit_order(self) -> Dict[str, Any]:
        raise PermissionError(
            "AR029 is dry-run only: submit_order is intentionally disabled"
        )
