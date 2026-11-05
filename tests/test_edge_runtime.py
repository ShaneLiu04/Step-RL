"""AR007: dynamic checkout drift and replanning inputs."""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.planner import CatalogItem, fetch_catalog, plan_instruction
from step_rl.edge.site import LocalShopServer

D1 = "买两件蓝牙耳机；如果缺货，就买两件USB-C数据线，并结算"
D2 = "预算300元，买无线充电器；如果超预算，就买USB-C数据线，并结算"


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


def test_stock_drop_rejects_order_and_updates_catalog():
    server = LocalShopServer(checkout_stock_drop={"p4": 1}).start()
    try:
        get, post = _client(server)
        get("/add/p4?qty=2")
        get("/checkout")
        with pytest.raises(urllib.error.HTTPError):
            post("/place-order", {"name": "A", "address": "B"})
        catalog = fetch_catalog(server.base_url)
        assert next(c for c in catalog if c.pid == "p4").stock == 1
    finally:
        server.stop()


def test_price_override_rejects_budget_order():
    server = LocalShopServer(
        checkout_price_override={"p3": 350}, checkout_budget=300
    ).start()
    try:
        get, post = _client(server)
        get("/add/p3?qty=1")
        get("/checkout")
        with pytest.raises(urllib.error.HTTPError):
            post("/place-order", {"name": "A", "address": "B"})
        catalog = fetch_catalog(server.base_url)
        assert next(c for c in catalog if c.pid == "p3").price == 350
    finally:
        server.stop()


def _catalog(p4_stock=9, p3_price=199):
    return [
        CatalogItem("p1", "iPhone 15 智能手机", 6999, 9, ("iphone", "手机", "apple")),
        CatalogItem("p2", "USB-C 快充数据线", 59, 9, ("usb", "数据线", "cable")),
        CatalogItem("p3", "无线充电器", p3_price, 9, ("无线", "充电器")),
        CatalogItem("p4", "蓝牙降噪耳机", 399, p4_stock, ("蓝牙", "耳机")),
    ]


def test_stock_replan_changes_targets():
    assert plan_instruction(D1, _catalog()).targets == {"p4": 2}
    assert plan_instruction(D1, _catalog(p4_stock=1)).targets == {"p2": 2}


def test_budget_replan_changes_targets():
    assert plan_instruction(D2, _catalog()).targets == {"p3": 1}
    assert plan_instruction(D2, _catalog(p3_price=350)).targets == {"p2": 1}
