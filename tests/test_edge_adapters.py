"""AR029: adapter contract, local golden, JD safety/helpers."""

from __future__ import annotations

import asyncio
import json

import pytest

from step_rl.edge.adapters.base import Action
from step_rl.edge.adapters.evidence import EvidenceWriter, redact
from step_rl.edge.adapters.jd import (
    JDAdapter,
    extract_amount,
    is_checkout_url,
    jd_search_url,
)
from step_rl.edge.adapters.local import LocalAdapter
from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TASK_BY_ID


async def _local_adapter():
    server = LocalShopServer().start()
    adapter = LocalAdapter(server, channel="msedge", headless=True, semantic=True)
    try:
        await adapter.open_session()
        return server, adapter
    except Exception as exc:  # pragma: no cover
        server.stop()
        pytest.skip(f"browser unavailable: {exc}")


def test_local_adapter_golden_contract():
    async def run():
        server, adapter = await _local_adapter()
        try:
            obs = await adapter.reset(TASK_BY_ID["sft_search_p1"])
            assert obs.page_type == "home"
            assert obs.elements
            catalog = await adapter.catalog()
            promos = await adapter.promos()
            assert any(item["pid"] == "p3" for item in catalog)
            assert any(item["code"] == "man400jian50" for item in promos)
            result = await adapter.execute(Action("goto", {"url": "/cart"}))
            assert result.ok
            cart = await adapter.observe()
            assert cart.page_type == "cart"
            verification = await adapter.verify(TASK_BY_ID["sft_search_p1"])
            assert verification.success is False
            assert "search_done" in verification.predicates
        finally:
            await adapter.close()
            server.stop()

    asyncio.run(run())


def test_jd_helpers_are_real_and_safe():
    assert jd_search_url("无线 充电器").startswith(
        "https://search.jd.com/Search?keyword="
    )
    assert is_checkout_url("https://trade.jd.com/shopping/order/getOrderInfo.action")
    assert is_checkout_url("https://item.jd.com/100.html") is False
    assert extract_amount("合计：￥119.00 优惠 -10") == 119.0
    assert extract_amount("无金额") is None


def test_jd_submit_is_disabled_in_dry_run():
    adapter = JDAdapter(allow_submit=False)
    with pytest.raises(PermissionError):
        asyncio.run(adapter.submit_order())


def test_evidence_writer_redacts_secrets(tmp_path):
    writer = EvidenceWriter(tmp_path, "run1", "jd")
    writer.step(
        {
            "action": "login",
            "password": "super-secret",
            "note": "cookie=abc123 token=xyz",
        }
    )
    payload = json.loads(writer.steps_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["password"] == "<redacted>"
    assert "super-secret" not in writer.steps_path.read_text(encoding="utf-8")
    assert redact({"token": "abc"})["token"] == "<redacted>"
    assert redact({"pt_key": "jd-secret", "thor": "x"})["pt_key"] == "<redacted>"
    assert redact({"thor": "x"})["thor"] == "<redacted>"


def test_evidence_writer_blocks_path_traversal(tmp_path):
    writer = EvidenceWriter(tmp_path, "../../escape", "../site")
    assert writer.root.parent == tmp_path / "site"
    assert writer.root.name == "escape"
    assert ".." not in str(writer.root.relative_to(tmp_path))


def test_evidence_writer_paths(tmp_path):
    writer = EvidenceWriter(tmp_path, "run2", "jd")
    png = writer.screenshot(b"png", "cart")
    html = writer.html("<html>cart</html>", "cart")
    report = writer.summary({"status": "ok", "cookie": "secret"})
    assert png.exists() and html.exists() and report.exists()
    assert "secret" not in report.read_text(encoding="utf-8")
