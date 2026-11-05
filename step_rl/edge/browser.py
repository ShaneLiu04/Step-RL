"""Real browser environment backed by Playwright + system Edge.

The environment drives the actual local shop over HTTP.  It never fabricates
observations or success: every action is executed by Chromium/Edge and every
state transition is read back from the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .site import LocalShopServer
from .tasks import TaskSpec

ACTION_WHITELIST = {"click", "type", "goto", "scroll", "wait", "finish"}

_OBSERVE_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll(
    "a,button,input,select,textarea,[role=button]"
  );
  const cssPath = (el) => {
    if (el.id) return "#" + CSS.escape(el.id);
    if (el.getAttribute("name")) {
      return el.tagName.toLowerCase() + '[name="' +
        CSS.escape(el.getAttribute("name")) + '"]';
    }
    if (el.getAttribute("data-testid")) {
      return '[data-testid="' + CSS.escape(el.getAttribute("data-testid")) + '"]';
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 5) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift("#" + CSS.escape(cur.id)); break; }
      const parent = cur.parentElement;
      if (parent) {
        const idx = Array.from(parent.children).indexOf(cur) + 1;
        part += ":nth-child(" + idx + ")";
      }
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };
  const roleOf = (el) => {
    const explicit = (el.getAttribute("role") || "").toLowerCase();
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      if (type === "number") return "spinbutton";
      if (type === "submit" || type === "button") return "button";
      return "textbox";
    }
    return tag;
  };
  let counter = 0;
  for (const el of nodes) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const selector = cssPath(el);
    if (!selector || seen.has(selector)) continue;
    seen.add(selector);
    counter += 1;
    const eid = "e" + counter;
    el.setAttribute("data-eid", eid);
    const accessible = (
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      (el.innerText || el.textContent || "").trim() ||
      el.getAttribute("name") ||
      (el.getAttribute("value") || "")
    ).trim().slice(0, 80);
    out.push({
      eid,
      selector,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute("type") || "").toLowerCase(),
      text: (el.innerText || el.textContent || "").trim().slice(0, 80),
      placeholder: el.getAttribute("placeholder") || "",
      name: el.getAttribute("name") || "",
      value: "value" in el ? String(el.value || "").slice(0, 80) : "",
      role: roleOf(el),
      accessible_name: accessible,
    });
  }
  return out;
}
"""


class BrowserEnv:
    def __init__(
        self,
        server: LocalShopServer,
        channel: str = "msedge",
        headless: bool = True,
        viewport: Optional[Dict[str, int]] = None,
        action_timeout_ms: int = 5000,
        max_elements: int = 24,
        perturb_ids: bool = False,
        semantic: bool = False,
        perturb_prob: float = 1.0,
    ) -> None:
        self.server = server
        self.channel = channel
        self.headless = headless
        self.viewport = viewport or {"width": 1100, "height": 800}
        self.action_timeout_ms = action_timeout_ms
        self.max_elements = max_elements
        self.perturb_ids = perturb_ids
        self.semantic = semantic
        self.perturb_prob = perturb_prob
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self.current_url = ""
        self.step_count = 0

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kwargs: Dict[str, Any] = {"headless": self.headless}
        if self.channel:
            launch_kwargs["channel"] = self.channel
        executable = os.environ.get("STEP_RL_BROWSER_PATH")
        if executable:
            launch_kwargs.pop("channel", None)
            launch_kwargs["executable_path"] = executable
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(viewport=self.viewport)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.action_timeout_ms)

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

    async def reset(self, task: TaskSpec) -> Dict[str, Any]:
        if self._page is None:
            await self.start()
        await self._page.goto(urljoin(self.server.base_url, "/api/reset"))
        self.step_count = 0
        await self._page.goto(urljoin(self.server.base_url, task.start_path))
        await self._settle()
        self.current_url = self._page.url
        return await self.observe()

    # -- observation ------------------------------------------------------
    async def _settle(self) -> None:
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.12)

    async def observe(self) -> Dict[str, Any]:
        if self._page is None:
            raise RuntimeError("BrowserEnv not started")
        self.current_url = self._page.url
        elements: List[Dict[str, str]] = await self._page.evaluate(_OBSERVE_JS)
        # Keep the most actionable elements first, deterministically.
        priority = {"input": 0, "button": 1, "a": 2, "select": 3, "textarea": 4}
        elements.sort(key=lambda e: (priority.get(e["tag"], 9), e["selector"]))
        elements = elements[: self.max_elements]
        body_text = ""
        try:
            body_text = (await self._page.inner_text("body"))[:600]
        except Exception:
            pass
        state = await self.get_state()
        observation = {
            "url": self.page_url_path,
            "title": await self._page.title(),
            "elements": elements,
            "text": body_text,
            "state": state,
        }
        # Stress test: mutate ids *after* the observation snapshot.  Legacy
        # selector actions become stale; semantic data-eid handles remain.
        if self.perturb_ids and random.random() < self.perturb_prob:
            await self._randomize_ids()
        return observation

    async def _randomize_ids(self) -> None:
        await self._page.evaluate(
            """() => {
                for (const el of document.querySelectorAll('[id]')) {
                    el.id = 'x' + Math.random().toString(36).slice(2, 10);
                }
            }"""
        )

    @property
    def page_url_path(self) -> str:
        parsed = urlparse(self._page.url)
        path = parsed.path or "/"
        return path + (f"?{parsed.query}" if parsed.query else "")

    async def get_state(self) -> Dict[str, Any]:
        try:
            data = await self._page.evaluate(
                "() => fetch('/api/state').then(r => r.json())"
            )
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # -- actions ----------------------------------------------------------
    async def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        name = str(action.get("action", "")).lower()
        params = action.get("params") or {}
        result: Dict[str, Any] = {
            "action": name,
            "params": params,
            "ok": False,
            "terminal": False,
            "error": "",
        }
        if name not in ACTION_WHITELIST:
            result["error"] = f"action not allowed: {name}"
            return result
        if not isinstance(params, dict):
            result["error"] = "params must be an object"
            return result
        self.step_count += 1
        try:
            if name == "goto":
                target = str(params.get("url", "/"))
                if not self._url_allowed(target):
                    result["error"] = "url blocked"
                    return result
                await self._page.goto(urljoin(self.server.base_url, target))
                await self._settle()
                result["ok"] = True
            elif name in ("click", "type"):
                element = params.get("element")
                if element:
                    selector = f'[data-eid="{element}"]'
                else:
                    selector = str(params.get("selector", ""))
                locator = self._page.locator(selector)
                count = await locator.count()
                if count != 1:
                    result["error"] = f"selector matched {count} elements"
                    return result
                if name == "click":
                    await locator.click(timeout=self.action_timeout_ms)
                    await self._settle()
                else:
                    text = str(params.get("text", ""))
                    await locator.fill(text, timeout=self.action_timeout_ms)
                result["ok"] = True
            elif name == "scroll":
                amount = _clamp_int(params.get("amount", 400), -2000, 2000)
                await self._page.evaluate(f"window.scrollBy(0, {amount})")
                result["ok"] = True
            elif name == "wait":
                ms = _clamp_int(params.get("duration_ms", 300), 0, 5000)
                await asyncio.sleep(ms / 1000.0)
                result["ok"] = True
            elif name == "finish":
                result["ok"] = True
                result["terminal"] = True
        except Exception as exc:  # real execution failure is surfaced
            result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        self.current_url = self._page.url if self._page else self.current_url
        return result

    def _url_allowed(self, target: str) -> bool:
        parsed = urlparse(urljoin(self.server.base_url, target))
        return (
            parsed.scheme in ("http", "https") and parsed.hostname == self.server.host
        )


def _clamp_int(value: Any, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(low, min(high, number))


def dump_observation(obs: Dict[str, Any]) -> str:
    return json.dumps(obs, ensure_ascii=False, indent=2)
