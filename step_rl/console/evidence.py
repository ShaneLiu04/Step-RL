"""Evidence Lab payload: live numbers from ``docs/results`` plus curated milestones.

Curated figures are copied verbatim from the archived AR / EX reports; the
``source`` field of every entry names the report that backs it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

RESULTS = Path(__file__).resolve().parent.parent.parent / "docs" / "results"

MILESTONES: List[Dict[str, Any]] = [
    {
        "failure": "奖励稀疏，数量控制学不会",
        "ars": "AR001 · AR003 · AR004",
        "before": "单策略 77.8%",
        "after": "层级 + 语义 100%",
        "value": "验证器 Φ → 步奖励 → 层级策略主干",
        "layer": "训练",
    },
    {
        "failure": "DOM 改版后动作失效",
        "ars": "AR004 · AR005",
        "before": "selector 0%",
        "after": "语义接口 100%",
        "value": "动作与 CSS 解耦为语义 data-eid",
        "layer": "接地",
    },
    {
        "failure": "用户约束被静默丢弃",
        "ars": "AR006 · AR023",
        "before": "naive 0/8",
        "after": "规划 8/8",
        "value": "券 / 预算 / 最值成为一等约束",
        "layer": "规划",
    },
    {
        "failure": "故障与库存漂移不可恢复",
        "ars": "AR007 · AR009 · AR014",
        "before": "单次执行",
        "after": "重规划 2/2 · 检查点 3/3",
        "value": "可观察、可恢复的运行时闭环",
        "layer": "运行时",
    },
    {
        "failure": "多订单失败补偿不一致",
        "ars": "AR016 · AR017 · AR018",
        "before": "0/3",
        "after": "3/3",
        "value": "有上界、可审计、可回滚的长事务",
        "layer": "事务",
    },
    {
        "failure": "变换与结算 / 券割裂",
        "ars": "AR027 · AR028",
        "before": "baseline 0/3",
        "after": "COT 3/3 · 0 LLM",
        "value": "变换 → 券预检 → 结算 → 失败回滚",
        "layer": "事务",
    },
    {
        "failure": "技能不能自进化",
        "ars": "AR019 – AR022 · AR034",
        "before": "永久依赖 LLM",
        "after": "归纳后 3/3 · 0 LLM",
        "value": "失败 → 兜底 → 归纳 → 统计淘汰",
        "layer": "自进化",
    },
    {
        "failure": "端侧成本高、并发串扰",
        "ars": "AR010 – AR012 · AR024 · AR025",
        "before": "GPU 依赖",
        "after": "30/30 · 0 GPU · 4/4 零串扰",
        "value": "技能编译 + CPU-first + 并发隔离",
        "layer": "系统",
    },
    {
        "failure": "异构布局不可迁移",
        "ars": "AR005 · AR026",
        "before": "固定技能 1/3",
        "after": "LASC 3/3",
        "value": "按实时控件能力编译动作",
        "layer": "接地",
    },
]

ABLATIONS: List[Dict[str, Any]] = [
    {"label": "语义接口 · DOM churn 1.0", "value": 100, "baseline": 0, "baseline_label": "selector", "source": "EX002 E1"},
    {"label": "层级分解 · 长链路", "value": 100, "baseline": 88.9, "baseline_label": "扁平", "source": "EX002 E2"},
    {"label": "验证器观测 · 保留", "value": 100, "baseline": 33.3, "baseline_label": "移除后", "source": "EX002 E3"},
    {"label": "约束规划准确率", "value": 100, "baseline": 0, "baseline_label": "naive", "source": "AR006"},
    {"label": "购物车→订单事务", "value": 100, "baseline": 0, "baseline_label": "baseline", "source": "AR028"},
]


def _load(name: str) -> Any:
    path = RESULTS / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_evidence() -> Dict[str, Any]:
    unified = _load("AR011_unified_summary.json") or {}
    rows = _load("AR011_unified_results.json") or []
    cpu = (_load("AR012_cpu_results.json") or {}).get("summary", {})
    serial = cpu.get("serial_12_seconds")
    concurrent = cpu.get("concurrent4_12_seconds")
    speedup = round(serial / concurrent, 2) if serial and concurrent else None
    headline = [
        {
            "label": "统一运行时",
            "value": f"{round(unified.get('success_rate', 0) * unified.get('tasks', 0))}/{unified.get('tasks', 0)}",
            "detail": f"{unified.get('skill_steps', 0)} 技能步 · {unified.get('prompt_tokens', 0)} tokens",
            "source": "AR011",
        },
        {
            "label": "LLM 调用",
            "value": str(unified.get("policy_steps", 0)),
            "detail": "覆盖任务全部由编译技能执行",
            "source": "AR011",
        },
        {
            "label": "4 路并发加速",
            "value": f"{speedup}×" if speedup else "—",
            "detail": f"串行 {serial}s → 并发 {concurrent}s · 0 GPU",
            "source": "AR012",
        },
        {
            "label": "观测往返",
            "value": "−62.7%",
            "detail": "单往返快照 + DOM 修订号缓存",
            "source": "AR025",
        },
    ]
    scenarios = [
        {
            "instruction": row.get("instruction", ""),
            "layout": row.get("layout", "v1"),
            "perturb": bool(row.get("perturb_ids")),
            "success": bool(row.get("success")),
            "steps": row.get("skill_steps", row.get("steps", 0)),
            "seconds": row.get("seconds", 0),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "headline": headline,
        "milestones": MILESTONES,
        "ablations": ABLATIONS,
        "scenarios": scenarios,
        "attempts": {"total": 28, "kept": 27, "archived": 1},
    }
