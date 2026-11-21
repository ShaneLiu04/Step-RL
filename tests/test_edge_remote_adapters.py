"""AR030: Taobao/Amazon read-only adapters and safety helpers."""

from __future__ import annotations

from step_rl.edge.adapters.amazon import AmazonAdapter
from step_rl.edge.adapters.base import Action
from step_rl.edge.adapters.remote import blocked_reason, parse_amount
from step_rl.edge.adapters.taobao import TaobaoAdapter


def test_remote_search_urls():
    tb = TaobaoAdapter()
    amz = AmazonAdapter()
    assert tb.search_url("无线充电器").startswith("https://s.taobao.com/search?q=")
    assert amz.search_url("usb cable").startswith("https://www.amazon.com/s?k=")
    assert "%E6%97%A0%E7%BA%BF" in tb.search_url("无线")


def test_remote_amount_and_blocks():
    assert parse_amount("价格 ¥199.00") == 199.0
    assert parse_amount("price $19.99") == 19.99
    assert blocked_reason("https://login.taobao.com/x", "登录", "") == "login_required"
    assert blocked_reason("https://x", "安全验证", "请完成验证码") == "captcha_or_risk_control"
    assert blocked_reason("https://s.taobao.com/search", "淘宝", "商品") == ""


def test_remote_is_read_only():
    import asyncio

    taobao = TaobaoAdapter()
    result = asyncio.run(taobao.execute(Action("click", {"element": "e1"})))
    assert result.ok is False
    assert result.error.startswith("read-only")
    assert taobao.capabilities.read
    assert not taobao.capabilities.cart
