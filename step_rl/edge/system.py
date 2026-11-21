"""Hybrid system entry: deterministic runtime + optional end-side LLM (AR033)."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .adapters.evidence import EvidenceWriter
from .adapters.registry import create_adapter
from .browser import BrowserEnv
from .runtime import run_task
from .site import LocalShopServer
from .tasks import TaskSpec


class HybridSystem:
    """One entry for deterministic local execution and read-only remote checks."""

    async def run_local(
        self,
        instruction: str,
        *,
        seed_cart: Optional[Dict[str, int]] = None,
        start_path: str = "/",
        model=None,
        tokenizer=None,
        model_name: str = "",
        evidence: Optional[EvidenceWriter] = None,
        capture: bool = True,
    ) -> Dict[str, Any]:
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        started = time.time()
        try:
            await env.start()
            task = TaskSpec(
                task_id="system",
                level=3,
                goal=instruction,
                search_query="",
                targets={},
                start_path=start_path,
                seed_cart=seed_cart or {},
            )
            await env.reset(task)
            result = await run_task(env, instruction, model, tokenizer)
            state = await env.get_state()
            steps = result.get("steps", [])
            payload = {
                "site": "local",
                "instruction": instruction,
                "success": bool(result.get("success")),
                "fallback": bool(result.get("fallback", False)),
                "fallback_required": bool(result.get("fallback_required", False)),
                "model": model_name,
                "steps": len(steps),
                "policy_steps": sum(1 for step in steps if step.source == "policy"),
                "skill_steps": sum(1 for step in steps if step.source == "skill"),
                "prompt_tokens": sum(len(step.prompt_ids) for step in steps),
                "seconds": round(time.time() - started, 2),
                "cart": state.get("cart", {}),
                "orders": len(state.get("orders", [])),
                "observation": dict(env.observation_metrics),
            }
            if capture and env._page is not None:
                png = await env._page.screenshot()
                payload["screenshot_bytes"] = len(png)
                if evidence is not None:
                    evidence.screenshot(png, "final")
            if evidence is not None:
                evidence.step({"step": "local_run", **payload})
                for index, step in enumerate(steps):
                    evidence.step(
                        {
                            "step": (
                                "policy_step"
                                if step.source == "policy"
                                else "skill_step"
                            ),
                            "index": index,
                            "source": step.source,
                            "action": step.action,
                            "exec_ok": step.exec_ok,
                            "error": step.error,
                        }
                    )
            return payload
        finally:
            await env.close()
            server.stop()

    async def run_remote(self, site: str, query: str) -> Dict[str, Any]:
        adapter = create_adapter(site, headless=True)
        started = time.time()
        payload = {"site": site, "query": query, "ok": False}
        try:
            storage = None
            if hasattr(adapter, "default_storage_state"):
                storage = adapter.default_storage_state()
            await adapter.open_session(storage_state=storage, manual_login=False)
            obs = await adapter.search(query)
            payload = {
                "site": site,
                "query": query,
                "title": obs.title,
                "url": obs.url,
                "page_type": obs.page_type,
                "blocked": obs.signals.get("blocked", ""),
                "elements": len(obs.elements),
                "seconds": round(time.time() - started, 2),
                "ok": not bool(obs.signals.get("blocked")) and bool(obs.title),
            }
            if hasattr(adapter, "product_links"):
                try:
                    links = await adapter.product_links()
                    payload["item_links"] = len(links)
                    if not links:
                        payload["ok"] = False
                        payload["error"] = "search page has no product links"
                except Exception as exc:
                    payload["item_links"] = 0
                    payload["ok"] = False
                    payload["error"] = (
                        f"product_links failed: {type(exc).__name__}: {exc}"
                    )
            return payload
        except Exception as exc:
            payload["seconds"] = round(time.time() - started, 2)
            payload["error"] = f"{type(exc).__name__}: {exc}"
            return payload
        finally:
            await adapter.close()
