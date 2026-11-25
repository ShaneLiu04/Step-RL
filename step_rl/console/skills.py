"""Skill Library payload: compiled skills, live induced registry and statistics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from ..edge.skill_library import induced_candidates, induced_operations
from ..edge.skill_stats import get_skill_stat

SKILL_MEMORY = Path(__file__).resolve().parent.parent / "edge" / "skill_memory.json"

COMPILED: List[Dict[str, Any]] = [
    {
        "name": "search",
        "title": "搜索商品",
        "kind": "compiled",
        "steps": ["输入关键词", "点击搜索"],
        "summary": "语义定位搜索框（id / 可访问名 / searchbox 角色），跨三代布局复用。",
        "evidence": "AR001 · AR026",
    },
    {
        "name": "add_item",
        "title": "加入购物车 · 数量自适应",
        "kind": "compiled",
        "steps": ["打开商品", "设置数量", "加入购物车"],
        "summary": "按实时控件能力编译数量操作：输入框、步进器或重复点击。",
        "evidence": "AR010 · AR026",
    },
    {
        "name": "update_quantity",
        "title": "购物车改量",
        "kind": "compiled",
        "steps": ["定位购物车行", "改写数量", "服务端复核"],
        "summary": "逐项以服务端状态复核，瞬时故障有界重试。",
        "evidence": "AR015 · AR018",
    },
    {
        "name": "checkout",
        "title": "结算 · 券约束",
        "kind": "compiled",
        "steps": ["进入结算", "领取满减券", "填写收货信息", "提交订单"],
        "summary": "券门槛对照实时价预检，不可行显式放弃，折扣由服务端权威结算。",
        "evidence": "AR023",
    },
    {
        "name": "cart_transform",
        "title": "购物车事务编译 (CTC)",
        "kind": "transaction",
        "steps": ["读取购物车", "计算目标量", "逐项改写", "失败回滚"],
        "summary": "加倍 / 统一改量 / 每件加一作为一个事务，已改项故障时补偿。",
        "evidence": "AR027",
    },
    {
        "name": "cart_to_order",
        "title": "购物车→订单事务 (COT)",
        "kind": "transaction",
        "steps": ["整体变换", "券预检", "结算", "订单失败取消"],
        "summary": "变换、用券与下单串成一个可补偿事务，门槛不足时 0 动作。",
        "evidence": "AR028",
    },
    {
        "name": "order_query",
        "title": "订单状态查询",
        "kind": "induced",
        "steps": ["进入订单页", "读取服务端状态谓词"],
        "summary": "LLM 兜底 1 步沉淀为技能，含取消态迁移与 ID churn。",
        "evidence": "AR022",
    },
    {
        "name": "remove",
        "title": "购物车移除 · 自愈归纳",
        "kind": "induced",
        "steps": ["进入购物车", "定位商品", "移除并复核"],
        "summary": "未覆盖时由端侧 LLM 成功一次，轨迹自动参数化注册，此后 0 LLM。",
        "evidence": "AR019 · AR020 · AR034",
    },
]


def _memory_summary() -> Dict[str, Any]:
    try:
        records = json.loads(SKILL_MEMORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        records = []
    pages = Counter(str(item.get("page_type", "other")) for item in records)
    return {"records": len(records), "pages": dict(pages)}


def build_skills() -> Dict[str, Any]:
    induced: List[Dict[str, Any]] = []
    for operation in induced_operations():
        for candidate in induced_candidates(operation):
            stat = get_skill_stat(candidate["name"])
            induced.append(
                {
                    "operation": operation,
                    "name": candidate["name"],
                    "steps": len(candidate.get("steps", [])),
                    "registered_at": candidate.get("registered_at", ""),
                    "attempts": stat.attempts if stat else 0,
                    "successes": stat.successes if stat else 0,
                    "success_rate": round(stat.success_rate, 3) if stat else None,
                    "demoted": bool(stat.demoted) if stat else False,
                }
            )
    return {"compiled": COMPILED, "induced": induced, "memory": _memory_summary()}
