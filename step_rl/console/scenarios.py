"""Curated Studio scenarios: real tasks the deterministic runtime covers with 0 LLM.

Every preset maps to an evaluated capability (see ``docs/results``); server
fixtures such as stock overrides or alternative layouts are whitelisted here
and never accepted from the client.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    subtitle: str
    instruction: str
    capability: str
    evidence: str
    icon: str
    start_path: str = "/"
    seed_cart: Dict[str, int] = field(default_factory=dict)
    layout: str = "v1"
    server_kwargs: Dict[str, Any] = field(default_factory=dict)
    # Independent verifier target: final server-side order items (and coupon).
    expect: Dict[str, int] = field(default_factory=dict)
    expect_promo: str = ""
    cart_transform: str = ""

    def public(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("server_kwargs")
        data["fixtures"] = sorted(self.server_kwargs)
        return data


SCENARIOS: Dict[str, Scenario] = {
    item.id: item
    for item in (
        Scenario(
            id="budget-bundle",
            title="预算约束组合购买",
            subtitle="预算 650 元内买两件商品并结算",
            instruction="预算650元，买无线充电器和蓝牙耳机各一件，并结算",
            capability="约束规划 · 多商品 · 结算",
            evidence="AR006 / AR011",
            icon="i-target",
            expect={"p3": 1, "p4": 1},
        ),
        Scenario(
            id="cart-to-order",
            title="购物车→订单事务",
            subtitle="整体加倍 + 满400减50 + 服务端结算",
            instruction="把购物车里的所有商品数量都加倍，并使用满400减50优惠结算",
            capability="购物车事务编译 · 券约束 · 补偿回滚",
            evidence="AR027 / AR028",
            icon="i-cart",
            start_path="/cart",
            seed_cart={"p3": 1, "p4": 1},
            expect={"p3": 2, "p4": 2},
            expect_promo="man400jian50",
            cart_transform="double",
        ),
        Scenario(
            id="price-ceiling",
            title="最值约束选购",
            subtitle="买 300 元以内最贵的商品",
            instruction="买价格不超过300元的最贵商品并结算",
            capability="语义规划 · 价格最值",
            evidence="AR006 / AR011",
            icon="i-spark",
            expect={"p3": 1},
        ),
        Scenario(
            id="stockout-fallback",
            title="缺货条件分支",
            subtitle="无线充电器缺货时自动改买耳机",
            instruction="如果无线充电器缺货，就买蓝牙耳机，并结算",
            capability="条件规划 · 实时库存",
            evidence="AR007 / AR011",
            icon="i-branch",
            server_kwargs={"stock_overrides": {"p3": 0}},
            expect={"p4": 1},
        ),
        Scenario(
            id="layout-v3",
            title="全新布局自适应",
            subtitle="v3 DOM：无 id、数量步进器，技能实时编译",
            instruction="买两件USB-C数据线并结算",
            capability="布局自适应技能编译 (LASC)",
            evidence="AR026",
            icon="i-layers",
            layout="v3",
            expect={"p2": 2},
        ),
        Scenario(
            id="multi-item",
            title="多商品一次结算",
            subtitle="iPhone 15 ×1 + 数据线 ×2",
            instruction="买一件iPhone 15和两件数据线，完成结算",
            capability="分层子任务 · 语义接地",
            evidence="AR003 / AR011",
            icon="i-stack",
            expect={"p1": 1, "p2": 2},
        ),
    )
}


def list_scenarios() -> List[Dict[str, Any]]:
    return [item.public() for item in SCENARIOS.values()]


def get_scenario(scenario_id: Optional[str]) -> Optional[Scenario]:
    if not scenario_id:
        return None
    return SCENARIOS.get(scenario_id)
