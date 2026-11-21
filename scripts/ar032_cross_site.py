"""AR032 cross-site read-only evaluation (real Edge, no mocks)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.adapters.amazon import AmazonAdapter  # noqa: E402
from step_rl.edge.adapters.evidence import EvidenceWriter  # noqa: E402
from step_rl.edge.adapters.jd import JDAdapter  # noqa: E402
from step_rl.edge.adapters.taobao import TaobaoAdapter  # noqa: E402
from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402

OUT = ROOT / "outputs" / "ar032" / "eval"
LOCAL_CASES = [
    "买两件无线充电器",
    "买一件蓝牙降噪耳机并结算",
    "买两件USB-C数据线并结算",
]


def storage_state() -> str:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(base) / "StepRL" / "credentials" / "jd.json")


async def run_local() -> list:
    rows = []
    for instruction in LOCAL_CASES:
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            await env.start()
            result = await run_task(env, instruction, None, None)
            rows.append(
                {
                    "site": "local",
                    "instruction": instruction,
                    "ok": bool(result.get("success")),
                    "steps": len(result.get("steps", [])),
                    "policy_steps": 0,
                    "prompt_tokens": 0,
                }
            )
        finally:
            await env.close()
            server.stop()
    return rows


async def run_remote(site: str, query: str, adapter_cls, storage: str = "") -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    writer = EvidenceWriter(ROOT / "outputs" / "ar032", run_id, site)
    kwargs = {"evidence": writer, "headless": True}
    if site == "jd":
        adapter = JDAdapter(**kwargs)
    else:
        adapter = adapter_cls(**kwargs)
    row = {"site": site, "query": query, "run_id": run_id, "ok": False}
    try:
        await adapter.open_session(
            storage_state=storage if site == "jd" else None,
            manual_login=False,
        )
        obs = await adapter.search(query)
        await adapter.capture("search")
        row.update(
            {
                "title": obs.title,
                "page_type": obs.page_type,
                "blocked": obs.signals.get("blocked", ""),
                "amount": obs.signals.get("amount"),
                "elements": len(obs.elements),
                "ok": not bool(obs.signals.get("blocked")),
            }
        )
        if not obs.title:
            row["ok"] = False
            row["error"] = "empty title (likely blocked/anti-bot or no content)"
        if site == "jd":
            try:
                links = await adapter.page.eval_on_selector_all(
                    "a",
                    "els => els.map(e => e.href).filter(h => /item\\.jd\\.com\\/\\d+\\.html/.test(h))",
                )
                row["item_links"] = len(links)
                if not links:
                    row["ok"] = False
                    row["error"] = "search page has no product links"
            except Exception:
                row["item_links"] = 0
                row["ok"] = False
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await adapter.close()
        writer.summary(row)
    return row


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    local = await run_local()
    remote = [
        await run_remote("jd", "无线充电器", JDAdapter, storage_state()),
        await run_remote("taobao", "无线充电器", TaobaoAdapter),
        await run_remote("amazon", "usb c cable", AmazonAdapter),
    ]
    payload = {
        "ar": "AR032",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "local": local,
        "remote": remote,
        "notes": (
            "Remote sites are read-only; no login bypass, no order/payment. "
            "Blocked/no-product results are failures, not success."
        ),
    }
    (OUT / "ar032_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
