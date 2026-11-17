"""AR025: adaptive observation cache on 30 real scenarios (real Edge, 0 LLM)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import ar011_eval as ar011  # noqa: E402
from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.planner import fetch_catalog  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS, TASK_BY_ID  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar025" / "eval"
BASE = ROOT / "outputs" / "ar025" / "baseline_probe.json"


async def run_case(
    model,
    tokenizer,
    instruction,
    expected,
    server_kwargs,
    layout,
    perturb,
    expected_task=None,
):
    server = LocalShopServer(layout=layout, **server_kwargs).start()
    env = BrowserEnv(
        server, channel="msedge", headless=True, semantic=True, perturb_ids=perturb
    )
    started = time.time()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = (
            expected_task
            if expected_task is not None
            else ar011.expected_spec(instruction, expected, catalog)
        )
        await env.start()
        result = await run_task(env, instruction, model, tokenizer)
        state = await env.get_state()
        success = compute_progress(state, env.page_url_path, spec).success
        metrics = dict(env.observation_metrics)
        return {
            "instruction": instruction,
            "expected": expected,
            "layout": layout,
            "perturb_ids": perturb,
            "success": success,
            "attempts": len(result["attempts"]),
            "fallback": result["fallback"],
            "steps": len(result["steps"]),
            "policy_steps": sum(
                1 for step in result["steps"] if step.source == "policy"
            ),
            "skill_steps": sum(1 for step in result["steps"] if step.source == "skill"),
            "prompt_tokens": sum(len(step.prompt_ids) for step in result["steps"]),
            "seconds": round(time.time() - started, 2),
            "observation": metrics,
        }
    finally:
        await env.close()
        server.stop()


async def cache_probe() -> dict:
    """Real no-op/wait observations must hit the cache, not force scans."""
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
        await env.reset(TASK_BY_ID["sft_search_p1"])
        first = await env.observe()
        second = await env.observe()
        assert (await env.execute({"action": "wait", "params": {"duration_ms": 50}}))[
            "ok"
        ]
        after_wait = await env.observe()
        metrics = dict(env.observation_metrics)
        same = first["elements"] == second["elements"] == after_wait["elements"]
        return {
            "metrics": metrics,
            "elements_stable": same,
            "state_live": bool(after_wait["state"]),
        }
    finally:
        await env.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    cache_check = await cache_probe()
    (OUT / "ar025_cache_probe.json").write_text(
        json.dumps(cache_check, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    model, tokenizer = load_multi_adapter(resolve_model_path(), ar011.ADAPTERS)
    rows = []
    for task in EVAL_TASKS:
        rows.append(
            await run_case(
                model,
                tokenizer,
                ar011.instruction_for(task),
                dict(task.targets),
                {},
                "v1",
                False,
                expected_task=task,
            )
        )
    for instruction, expected, stock in ar011.CONSTRAINT:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction,
                expected,
                {"stock_overrides": stock} if stock else {},
                "v1",
                False,
            )
        )
    for instruction, expected, server_kwargs in ar011.DYNAMIC:
        rows.append(
            await run_case(
                model, tokenizer, instruction, expected, server_kwargs, "v1", False
            )
        )
    for instruction, expected in ar011.ERROR:
        rows.append(
            await run_case(
                model,
                tokenizer,
                instruction,
                expected,
                {
                    "checkout_name_requires_title": True,
                    "checkout_address_requires_road": True,
                },
                "v1",
                False,
            )
        )
    for task in EVAL_TASKS:
        rows.append(
            await run_case(
                model,
                tokenizer,
                ar011.instruction_for(task),
                dict(task.targets),
                {},
                "v2",
                True,
                expected_task=task,
            )
        )

    (OUT / "ar025_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    count = max(1, len(rows))
    obs = {
        key: sum(row["observation"][key] for row in rows)
        for key in ("calls", "hits", "misses", "dom_scans", "roundtrips")
    }
    obs["seconds"] = round(sum(row["observation"]["seconds"] for row in rows), 2)
    summary = {
        "tasks": len(rows),
        "success_rate": sum(r["success"] for r in rows) / count,
        "policy_steps": sum(r["policy_steps"] for r in rows),
        "skill_steps": sum(r["skill_steps"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 2),
        "observation": obs,
    }
    baseline = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {}
    compare = {}
    if baseline:
        compare = {
            "observe_calls_baseline": baseline["observe_calls"],
            "observe_calls_ar025": obs["calls"],
            "roundtrips_baseline": baseline["observe_roundtrips"],
            "roundtrips_ar025": obs["roundtrips"],
            "roundtrip_reduction": round(
                1 - obs["roundtrips"] / max(1, baseline["observe_roundtrips"]), 4
            ),
            "observe_seconds_baseline": baseline["observe_seconds"],
            "observe_seconds_ar025": obs["seconds"],
            "observe_time_reduction": round(
                1 - obs["seconds"] / max(0.001, baseline["observe_seconds"]), 4
            ),
            "cache_hits": obs["hits"],
            "dom_scans": obs["dom_scans"],
        }
    verdict = {
        "P0_baseline": bool(baseline),
        "P1_30_scenarios": summary["success_rate"] == 1.0
        and summary["policy_steps"] == 0
        and summary["prompt_tokens"] == 0,
        "P2_roundtrips": compare.get("roundtrip_reduction", -1) >= 0.5,
        "P3_observe_time": compare.get("observe_time_reduction", -1) >= 0.25,
        "P4_cache_probe": cache_check["metrics"]["hits"] >= 2
        and cache_check["elements_stable"]
        and cache_check["state_live"],
    }
    verdict["overall"] = all(verdict.values())
    payload = {
        "ar": "AR025",
        "summary": summary,
        "baseline": baseline,
        "compare": compare,
        "cache_probe": cache_check,
        "verdict": verdict,
    }
    (OUT / "ar025_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR025 自适应观测缓存评测（真实 Edge / 30 场景 / 0 LLM）",
        "",
        f"- 成功率：{summary['success_rate']:.1%}",
        f"- LLM 步数：{summary['policy_steps']}；技能步数：{summary['skill_steps']}",
        f"- Prompt tokens：{summary['prompt_tokens']}",
        f"- 总耗时：{summary['seconds']:.1f}s",
        "",
        "## AOC 观测指标",
        "",
        "| 指标 | 基线 | AR025 | 变化 |",
        "|------|------|-------|------|",
        f"| observe 调用 | {compare.get('observe_calls_baseline', '-')} | "
        f"{obs['calls']} | - |",
        f"| 浏览器往返 | {compare.get('roundtrips_baseline', '-')} | "
        f"{obs['roundtrips']} | {compare.get('roundtrip_reduction', 0):.1%} 下降 |",
        f"| observe 耗时 | {compare.get('observe_seconds_baseline', '-')}s | "
        f"{obs['seconds']}s | {compare.get('observe_time_reduction', 0):.1%} 下降 |",
        f"| 缓存命中/扫描 | - | {obs['hits']} / {obs['dom_scans']} | - |",
        "",
        "## 独立缓存探针（重复 / wait 观测）",
        "",
        f"- 命中 {cache_check['metrics']['hits']} 次，扫描 "
        f"{cache_check['metrics']['dom_scans']} 次；元素稳定="
        f"{cache_check['elements_stable']}；state 实时={cache_check['state_live']}",
        "",
        "## 判定",
        "",
        "```json",
        json.dumps(verdict, ensure_ascii=False, indent=2),
        "```",
    ]
    (OUT / "ar025_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
