"""Constraint planner and stock enforcement tests."""

from __future__ import annotations

import urllib.error

import pytest

from step_rl.edge.planner import CatalogItem, naive_plan, plan_instruction
from step_rl.edge.site import LocalShopServer


def catalog(p3_stock: int = 9):
    return [
        CatalogItem("p1", "iPhone 15 智能手机", 6999, 9, ("iphone", "手机", "apple")),
        CatalogItem("p2", "USB-C 快充数据线", 59, 9, ("usb", "数据线", "cable", "充电")),
        CatalogItem("p3", "无线充电器", 199, p3_stock, ("无线", "充电器", "charger")),
        CatalogItem("p4", "蓝牙降噪耳机", 399, 5, ("蓝牙", "耳机", "headphone")),
    ]


def targets(instruction, p3_stock=9):
    spec = plan_instruction(instruction, catalog(p3_stock))
    return None if spec is None else spec.targets


def test_cheapest_and_most_expensive():
    assert targets("买最便宜的商品并结算") == {"p2": 1}
    assert targets("买最贵的商品并结算") == {"p1": 1}


def test_budget_constrained_most_expensive():
    assert targets("买价格不超过300元的最贵商品并结算") == {"p3": 1}


def test_quantity_and_multi_item():
    assert targets("买两件USB-C数据线并结算") == {"p2": 2}
    assert targets("买一件iPhone 15和两件数据线，完成结算") == {"p1": 1, "p2": 2}
    assert targets("买三件蓝牙耳机并结算") == {"p4": 3}


def test_budget_and_multiple_products():
    assert targets("预算650元，买无线充电器和蓝牙耳机各一件，并结算") == {
        "p3": 1,
        "p4": 1,
    }


def test_out_of_stock_substitution():
    assert targets("如果无线充电器缺货，就买蓝牙耳机，并结算", p3_stock=0) == {"p4": 1}


def test_naive_baseline_is_keyword_only():
    items = catalog()
    assert naive_plan("买最便宜的商品并结算", items) is None
    assert naive_plan("买两件USB-C数据线并结算", items).targets == {"p2": 1}
    assert naive_plan("买三件蓝牙耳机并结算", items).targets == {"p4": 1}


def test_stock_is_enforced_by_server():
    server = LocalShopServer(stock_overrides={"p3": 0}).start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(server.base_url + "/add/p3?qty=1")
    finally:
        server.stop()
