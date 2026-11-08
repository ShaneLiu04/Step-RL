"""AR009 form validation and error observability tests."""

from __future__ import annotations

import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.policy import build_prompt
from step_rl.edge.site import LocalShopServer


def _client(server):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(path):
        return opener.open(server.base_url + path).read().decode("utf-8")

    def post(path, data):
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            server.base_url + path, data=body, method="POST"
        )
        return opener.open(request).read().decode("utf-8")

    return get, post


def test_name_title_validation():
    server = LocalShopServer(checkout_name_requires_title=True).start()
    try:
        get, post = _client(server)
        get("/add/p3?qty=1")
        get("/checkout")
        with pytest.raises(urllib.error.HTTPError):
            post("/place-order", {"name": "刘星言", "address": "深圳路1号"})
        get("/checkout")
        post("/place-order", {"name": "刘星言先生", "address": "深圳路1号"})
    finally:
        server.stop()


def test_address_road_validation():
    server = LocalShopServer(checkout_address_requires_road=True).start()
    try:
        get, post = _client(server)
        get("/add/p3?qty=1")
        get("/checkout")
        with pytest.raises(urllib.error.HTTPError):
            post("/place-order", {"name": "刘星言先生", "address": "深圳市龙岗区"})
    finally:
        server.stop()


def test_page_notice_is_injected():
    prompt = build_prompt(
        "任务",
        {"url": "/checkout", "title": "结算", "elements": [], "state": {}},
        progress=0.8,
        missing=["name_filled"],
        page_notice="收货人需包含称谓（先生/女士）",
    )
    assert "页面提示" in prompt
    assert "称谓" in prompt
