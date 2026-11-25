"""Packaged evaluation suites for ``step-rl eval``.

* ``smoke``   — the six curated Studio scenarios (~1 min on a laptop).
* ``unified`` — the AR011 30-scenario regression gate (v1 + v2 layouts, ID churn,
  stock / price drift, form-error repair).

Every case runs on its own LocalShopServer + browser session, so cases can run
concurrently (AR024 isolation).  Success is judged by the verifier against the
case's *expected* targets on authoritative server state — never by the
runtime's own report.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..edge.site import PRODUCTS
from ..edge.tasks import EVAL_TASKS, TaskSpec

ROOT = Path(__file__).resolve().parent.parent.parent

_FORM_ERRORS = {"checkout_name_requires_title": True, "checkout_address_requires_road": True}


@dataclass
class Case:
    id: str
    instruction: str
    expect: Dict[str, int]
    layout: str = "v1"
    perturb_ids: bool = False
    server_kwargs: Dict[str, Any] = field(default_factory=dict)
    seed_cart: Dict[str, int] = field(default_factory=dict)
    start_path: str = "/"
    expect_promo: str = ""
    cart_transform: str = ""
    task: Optional[TaskSpec] = None
    group: str = ""

    def expected_spec(self) -> TaskSpec:
        if self.task is not None:
            return self.task
        first = PRODUCTS[next(iter(self.expect))]
        return TaskSpec(
            task_id=self.id,
            level=5 if len(self.expect) > 1 else 4,
            goal=self.instruction,
            search_query=first.keywords[0],
            targets=dict(self.expect),
            require_checkout=True,
            require_promo=bool(self.expect_promo),
            promo=self.expect_promo,
            cart_transform=self.cart_transform,
        )


def _instruction_for(task: TaskSpec) -> str:
    if task.level == 1:
        return f"搜索{PRODUCTS[next(iter(task.targets))].keywords[0]}"
    text = "，".join(f"买{qty}件{PRODUCTS[pid].name}" for pid, qty in task.targets.items())
    return text + ("，并结算" if task.require_checkout else "")


def smoke_cases() -> List[Case]:
    from ..console.scenarios import SCENARIOS

    return [
        Case(
            id=s.id,
            instruction=s.instruction,
            expect=dict(s.expect),
            layout=s.layout,
            server_kwargs=dict(s.server_kwargs),
            seed_cart=dict(s.seed_cart),
            start_path=s.start_path,
            expect_promo=s.expect_promo,
            cart_transform=s.cart_transform,
            group="studio",
        )
        for s in SCENARIOS.values()
    ]


def unified_cases() -> List[Case]:
    cases: List[Case] = []
    for task in EVAL_TASKS:
        cases.append(Case(f"v1-{task.task_id}", _instruction_for(task), dict(task.targets), task=task, group="held-out"))
    constraint = [
        ("买最便宜的商品并完成结算", {"p2": 1}, {}),
        ("买价格不超过300元的最贵商品并结算", {"p3": 1}, {}),
        ("买两件USB-C数据线并结算", {"p2": 2}, {}),
        ("买一件iPhone 15和两件数据线，完成结算", {"p1": 1, "p2": 2}, {}),
        ("预算650元，买无线充电器和蓝牙耳机各一件，并结算", {"p3": 1, "p4": 1}, {}),
        ("买三件蓝牙耳机并结算", {"p4": 3}, {}),
        ("买最贵的商品并结算", {"p1": 1}, {}),
        ("如果无线充电器缺货，就买蓝牙耳机，并结算", {"p4": 1}, {"p3": 0}),
    ]
    for i, (text, expect, stock) in enumerate(constraint, 1):
        kwargs = {"stock_overrides": stock} if stock else {}
        cases.append(Case(f"constraint-{i}", text, expect, server_kwargs=kwargs, group="constraint"))
    cases.append(Case("dynamic-stock", "买两件蓝牙耳机；如果缺货，就买两件USB-C数据线，并结算", {"p2": 2},
                      server_kwargs={"checkout_stock_drop": {"p4": 1}}, group="dynamic"))
    cases.append(Case("dynamic-price", "预算300元，买无线充电器；如果超预算，就买USB-C数据线，并结算", {"p2": 1},
                      server_kwargs={"checkout_price_override": {"p3": 350}, "checkout_budget": 300}, group="dynamic"))
    cases.append(Case("form-repair-1", "买一件无线充电器并结算", {"p3": 1}, server_kwargs=dict(_FORM_ERRORS), group="error"))
    cases.append(Case("form-repair-2", "买两件USB-C数据线并结算", {"p2": 2}, server_kwargs=dict(_FORM_ERRORS), group="error"))
    for task in EVAL_TASKS:
        cases.append(Case(f"v2-churn-{task.task_id}", _instruction_for(task), dict(task.targets), layout="v2",
                          perturb_ids=True, task=task, group="layout-v2 + id-churn"))
    return cases


SUITES: Dict[str, Callable[[], List[Case]]] = {"smoke": smoke_cases, "unified": unified_cases}


async def run_case(
    case: Case, *, channel: Optional[str] = None, headless: bool = True, trace: bool = False
) -> Dict[str, Any]:
    from ..edge.browser import BrowserEnv
    from ..edge.runtime import run_task
    from ..edge.site import LocalShopServer
    from ..edge.verifier import compute_progress

    channel = channel if channel is not None else os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge")
    server = LocalShopServer(layout=case.layout, **case.server_kwargs).start()
    env = BrowserEnv(server, channel=None if channel == "chromium" else channel, headless=headless,
                     semantic=True, perturb_ids=case.perturb_ids)
    started = time.perf_counter()
    row: Dict[str, Any] = {"id": case.id, "group": case.group, "instruction": case.instruction,
                           "layout": case.layout, "perturb_ids": case.perturb_ids}
    try:
        await env.start()
        await env.reset(TaskSpec(f"eval_{case.id}", 3, case.instruction, "", {},
                                 start_path=case.start_path, seed_cart=dict(case.seed_cart)))
        result = await run_task(env, case.instruction, None, None)
        state = await env.get_state()
        verdict = compute_progress(state, env.page_url_path, case.expected_spec())
        steps = result.get("steps", [])
        order = state.get("order") or {}
        row.update(
            success=verdict.success,
            runtime_reported=bool(result.get("success")),
            missing=list(verdict.missing),
            skill_steps=sum(1 for s in steps if getattr(s, "source", "") == "skill"),
            policy_steps=sum(1 for s in steps if getattr(s, "source", "") == "policy"),
            prompt_tokens=sum(len(getattr(s, "prompt_ids", []) or []) for s in steps),
            fallback_required=bool(result.get("fallback_required")),
            order_total=order.get("total"),
            order_paid=order.get("paid"),
            observation=dict(env.observation_metrics),
        )
        if trace:
            row["satisfied"] = list(verdict.satisfied)
            row["cart"] = dict(state.get("cart") or {})
            row["promo"] = (order.get("promo") or {}).get("code", "")
            row["trace"] = [
                {
                    "action": (getattr(s, "action", {}) or {}).get("action", "?"),
                    "params": (getattr(s, "action", {}) or {}).get("params", {}),
                    "ok": bool(getattr(s, "exec_ok", False)),
                    "source": getattr(s, "source", ""),
                }
                for s in steps
            ]
    except Exception as exc:
        row.update(success=False, error=f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}")
    finally:
        await env.close()
        server.stop()
    row["seconds"] = round(time.perf_counter() - started, 2)
    return row


async def run_suite(
    cases: List[Case],
    *,
    concurrency: int = 2,
    channel: Optional[str] = None,
    headless: bool = True,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(case: Case) -> Dict[str, Any]:
        async with gate:
            row = await run_case(case, channel=channel, headless=headless)
        if on_result:
            on_result(row)
        return row

    rows = await asyncio.gather(*(one(c) for c in cases))
    order = {c.id: i for i, c in enumerate(cases)}
    return sorted(rows, key=lambda r: order[r["id"]])


def summarize(rows: List[Dict[str, Any]], wall_seconds: float) -> Dict[str, Any]:
    n = max(1, len(rows))
    return {
        "cases": len(rows),
        "passed": sum(bool(r.get("success")) for r in rows),
        "success_rate": round(sum(bool(r.get("success")) for r in rows) / n, 4),
        "llm_steps": sum(r.get("policy_steps", 0) for r in rows),
        "skill_steps": sum(r.get("skill_steps", 0) for r in rows),
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rows),
        "case_seconds": round(sum(r.get("seconds", 0) for r in rows), 2),
        "wall_seconds": round(wall_seconds, 2),
        "errors": sum(1 for r in rows if r.get("error")),
    }


def write_report(suite: str, rows: List[Dict[str, Any]], summary: Dict[str, Any], out_dir: Optional[Path] = None) -> Path:
    out = out_dir or ROOT / "outputs" / "eval" / f"{suite}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"suite": suite, **summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# step-rl eval · {suite}",
        "",
        f"- 通过：**{summary['passed']}/{summary['cases']}**（{summary['success_rate']:.1%}）",
        f"- LLM 步数：{summary['llm_steps']} · 技能步数：{summary['skill_steps']} · prompt tokens：{summary['prompt_tokens']}",
        f"- 墙钟耗时：{summary['wall_seconds']}s（单例累计 {summary['case_seconds']}s）",
        "",
        "| 用例 | 分组 | 布局 | churn | 结果 | 技能步 | LLM 步 | 耗时 |",
        "|------|------|------|-------|------|--------|--------|------|",
    ]
    for r in rows:
        mark = "✓" if r.get("success") else ("✗ " + (r.get("error") or ",".join(r.get("missing", []))))[:60]
        lines.append(
            f"| {r['id']} | {r['group']} | {r['layout']} | {'是' if r['perturb_ids'] else '否'} | {mark} | "
            f"{r.get('skill_steps', 0)} | {r.get('policy_steps', 0)} | {r['seconds']}s |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def case_dict(case: Case) -> Dict[str, Any]:
    data = asdict(case)
    data.pop("task", None)
    return data
