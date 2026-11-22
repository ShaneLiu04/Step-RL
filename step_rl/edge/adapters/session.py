"""Shared real-browser session lifecycle for remote adapters (AR030+)."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional

from .evidence import EvidenceWriter


class BrowserSession:
    """Owns one Playwright context/page; subclasses add site semantics."""

    settle_seconds = 1.5

    def __init__(
        self,
        *,
        site_name: str,
        evidence: Optional[EvidenceWriter] = None,
        headless: bool = True,
        min_action_interval: float = 5.0,
        max_pages: int = 20,
    ) -> None:
        self.name = site_name
        self.evidence = evidence
        self.headless = headless
        self.min_action_interval = min_action_interval
        self.max_pages = max_pages
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self.page: Any = None
        self.pages_loaded = 0
        self._last_action = 0.0

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

    async def save_storage_state(self, path: str) -> None:
        if self._context is None:
            raise RuntimeError(f"{self.name} session not open")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(target))

    async def close(self) -> None:
        for obj in (self._context, self._browser):
            if obj:
                with suppress(Exception):
                    await obj.close()
        if self._pw:
            with suppress(Exception):
                await self._pw.stop()

    def _require(self):
        if self.page is None:
            raise RuntimeError(f"{self.name} session not open")
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
        await asyncio.sleep(self.settle_seconds)

    async def goto(self, url: str) -> None:
        self._require()
        self._rate_limit()
        self._count_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self._settle()

    async def capture(self, name: str) -> Dict[str, str]:
        page = self._require()
        result: Dict[str, str] = {}
        if self.evidence is not None:
            with suppress(Exception):
                result["screenshot"] = str(
                    self.evidence.screenshot(await page.screenshot(full_page=False), name)
                )
            with suppress(Exception):
                result["html"] = str(self.evidence.html(await page.content(), name))
        return result
