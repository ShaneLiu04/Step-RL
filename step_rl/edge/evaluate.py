"""Real evaluation matrix over held-out tasks.

Every number in the report comes from a real browser episode against the
local shop.  No hard-coded benchmark arrays are used.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .browser import BrowserEnv
from .modeling import DEFAULT_MODEL, load_policy, resolve_model_path
from .rollout import rollout_task
from .site import LocalShopServer
from .tasks import EVAL_TASKS, TaskSpec


async def evaluate_policy(
    label: str,
    adapter_path: Optional[str],
    *,
    model_name: str = DEFAULT_MODEL,
    repair: bool = True,
    tasks: Optional[List[TaskSpec]] = None,
    max_steps: int = 12,
    seed: int = 42,
    memory=None,
    memory_prompt: bool = False,
    replan: bool = False,
    perturb_ids: bool = False,
    semantic: bool = False,
    layout: str = "v1",
    perturb_prob: float = 1.0,
    verifier_hints: bool = True,
) -> Dict[str, Any]:
    from .modeling import set_seed

    set_seed(seed)
    tasks = tasks or EVAL_TASKS
    model, tokenizer = load_policy(
        resolve_model_path(model_name), adapter_path, trainable=False
    )
    server = LocalShopServer(layout=layout).start()
    env = BrowserEnv(
        server,
        channel="msedge",
        headless=True,
        perturb_ids=perturb_ids,
        semantic=semantic,
        perturb_prob=perturb_prob,
    )
    started = time.time()
    results = []
    try:
        await env.start()
        for task in tasks:
            rollout = await rollout_task(
                env,
                task,
                model,
                tokenizer,
                repair=repair,
                sample=False,
                max_steps=max_steps,
                reward_mode="vgdp",
                memory=memory,
                memory_prompt=memory_prompt,
                replan=replan,
                semantic=semantic,
                verifier_hints=verifier_hints,
            )
            results.append(
                {
                    "task_id": task.task_id,
                    "level": task.level,
                    "success": rollout.success,
                    "final_progress": rollout.final_progress,
                    "steps": rollout.total_steps,
                    "raw_invalid": rollout.raw_invalid,
                    "repaired": rollout.repaired,
                    "memory_replans": sum(
                        1 for step in rollout.steps if step.source == "memory_replan"
                    ),
                    "actions": [s.action for s in rollout.steps],
                    "sources": [s.source for s in rollout.steps],
                }
            )
    finally:
        await env.close()
        server.stop()

    count = max(1, len(results))
    summary = {
        "label": label,
        "repair": repair,
        "adapter": adapter_path,
        "model": resolve_model_path(model_name),
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "avg_progress": sum(r["final_progress"] for r in results) / count,
        "raw_invalid_rate": sum(1 for r in results if r["raw_invalid"] > 0) / count,
        "repair_rate": sum(1 for r in results if r["repaired"] > 0) / count,
        "seconds": round(time.time() - started, 2),
        "results": results,
    }
    return summary


async def run_matrix(
    configs: List[Dict[str, Any]],
    output_dir: str,
    *,
    model_name: str = DEFAULT_MODEL,
    tasks: Optional[List[TaskSpec]] = None,
    max_steps: int = 12,
) -> Dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for config in configs:
        label = config["label"]
        adapter = config.get("adapter")
        if adapter and not Path(adapter).exists():
            summaries.append(
                {
                    "label": label,
                    "skipped": True,
                    "reason": f"adapter not found: {adapter}",
                }
            )
            continue
        summary = await evaluate_policy(
            label,
            adapter,
            model_name=model_name,
            repair=bool(config.get("repair", True)),
            tasks=tasks,
            max_steps=max_steps,
        )
        summaries.append(summary)
        (output / f"{label}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"[eval] {label}: success={summary['success_rate']:.3f} "
            f"steps={summary['avg_steps']:.2f} invalid={summary['raw_invalid_rate']:.3f}",
            flush=True,
        )

    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.platform(),
        "model": resolve_model_path(model_name),
        "max_steps": max_steps,
        "summaries": summaries,
    }
    report["best"] = select_best(summaries)
    (output / "eval_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "eval_report.md").write_text(render_report(report), encoding="utf-8")
    return report


def select_best(summaries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    valid = [s for s in summaries if not s.get("skipped")]
    if not valid:
        return None
    return max(
        valid,
        key=lambda s: (
            s["success_rate"],
            s["avg_progress"],
            -s["avg_steps"],
            -s["raw_invalid_rate"],
        ),
    )


def render_report(report: Dict[str, Any]) -> str:
    lines = [
        "# AR001 真实评测报告",
        "",
        f"- 时间：{report['created_at']}",
        f"- 平台：{report['platform']}",
        f"- 模型：`{report['model']}`",
        f"- 最大步数：{report['max_steps']}",
        "",
        "## 指标对比",
        "",
        "| 组合 | 修复 | 成功率 | 平均步数 | 平均进度 | 原始非法率 | 修复率 |",
        "|------|------|--------|----------|----------|------------|--------|",
    ]
    for summary in report["summaries"]:
        if summary.get("skipped"):
            lines.append(
                f"| {summary['label']} | - | skipped | - | - | - | {summary['reason']} |"
            )
            continue
        lines.append(
            "| {label} | {repair} | {sr:.1%} | {steps:.2f} | {prog:.2f} | "
            "{inv:.1%} | {rep:.1%} |".format(
                label=summary["label"],
                repair="✓" if summary["repair"] else "✗",
                sr=summary["success_rate"],
                steps=summary["avg_steps"],
                prog=summary["avg_progress"],
                inv=summary["raw_invalid_rate"],
                rep=summary["repair_rate"],
            )
        )
    best = report.get("best")
    lines.extend(
        [
            "",
            "## 组合决策",
            "",
            f"最优组合：**{best['label']}**（成功率 {best['success_rate']:.1%}）"
            if best
            else "无可用组合。",
            "",
            "回退规则：按 `sft → sft_repair → sparse_grpo_repair → vgdp_grpo_repair`",
            "依次比较，只有严格不劣于当前最优才晋级；否则保留上一最优。",
            "",
            "## 逐任务结果",
            "",
            "| 任务 | 等级 | 成功 | 进度 | 步数 | 原始非法 | 修复 |",
            "|------|------|------|------|------|----------|------|",
        ]
    )
    for summary in report["summaries"]:
        if summary.get("skipped"):
            continue
        for task in summary["results"]:
            lines.append(
                "| {label}/{task} | L{level} | {ok} | {prog:.2f} | {steps} | {inv} | {rep} |".format(
                    label=summary["label"],
                    task=task["task_id"],
                    level=task["level"],
                    ok="✓" if task["success"] else "✗",
                    prog=task["final_progress"],
                    steps=task["steps"],
                    inv=task["raw_invalid"],
                    rep=task["repaired"],
                )
            )
    lines.append("")
    return "\n".join(lines)
