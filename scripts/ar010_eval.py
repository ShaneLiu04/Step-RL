"""AR010: compiled skills vs LLM-per-step execution."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.hierarchical import run_hierarchy  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import run_skill_hierarchy  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar010" / "eval"


async def run_condition(
    model,
    tokenizer,
    label: str,
    mode: str,
    layout: str = "v1",
    perturb: bool = False,
) -> dict:
    server = LocalShopServer(layout=layout).start()
    env = BrowserEnv(
        server,
        channel="msedge",
        headless=True,
        semantic=True,
        perturb_ids=perturb,
    )
    results = []
    started = time.time()
    try:
        await env.start()
        for task in EVAL_TASKS:
            if mode == "baseline":
                rollout = await run_hierarchy(
                    env,
                    task,
                    model,
                    tokenizer,
                    repair=False,
                    max_steps_per_subtask=12,
                    semantic=True,
                )
            else:
                rollout = await run_skill_hierarchy(
                    env,
                    task,
                    model,
                    tokenizer,
                    fallback=True,
                    semantic=True,
                    max_steps_per_subtask=12,
                )
            policy_steps = sum(1 for s in rollout.steps if s.source == "policy")
            skill_steps = sum(1 for s in rollout.steps if s.source == "skill")
            results.append(
                {
                    "task_id": task.task_id,
                    "level": task.level,
                    "success": rollout.success,
                    "steps": rollout.total_steps,
                    "policy_steps": policy_steps,
                    "skill_steps": skill_steps,
                    "prompt_tokens": sum(len(s.prompt_ids) for s in rollout.steps),
                    "generated_tokens": sum(len(s.response_ids) for s in rollout.steps),
                }
            )
            print(
                f"[{label}] {task.task_id}: success={rollout.success} "
                f"steps={rollout.total_steps} policy={policy_steps} "
                f"skill={skill_steps}",
                flush=True,
            )
    finally:
        await env.close()
        server.stop()
    count = max(1, len(results))
    return {
        "label": label,
        "layout": layout,
        "perturb_ids": perturb,
        "tasks": len(results),
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "policy_steps": sum(r["policy_steps"] for r in results),
        "skill_steps": sum(r["skill_steps"] for r in results),
        "prompt_tokens": sum(r["prompt_tokens"] for r in results),
        "generated_tokens": sum(r["generated_tokens"] for r in results),
        "seconds": round(time.time() - started, 2),
        "results": results,
    }


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    reports = []
    for label, mode, layout, perturb in (
        ("baseline_llm", "baseline", "v1", False),
        ("compiled_skill_v1", "skill", "v1", False),
        ("compiled_skill_v2_churn", "skill", "v2", True),
    ):
        report = await run_condition(model, tokenizer, label, mode, layout, perturb)
        reports.append(report)
        (OUT / f"{label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "results"},
                ensure_ascii=False,
            ),
            flush=True,
        )
    lines = [
        "# AR010 技能编译真实评测",
        "",
        "| 条件 | 布局 | churn | 成功率 | 平均步数 | LLM 步数 | 技能步数 | Prompt tokens |",
        "|------|------|-------|--------|----------|----------|----------|---------------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['layout']} | "
            f"{'是' if report['perturb_ids'] else '否'} | "
            f"{report['success_rate']:.1%} | {report['avg_steps']:.2f} | "
            f"{report['policy_steps']} | {report['skill_steps']} | "
            f"{report['prompt_tokens']} |"
        )
    lines.append("")
    (OUT / "ar010_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
