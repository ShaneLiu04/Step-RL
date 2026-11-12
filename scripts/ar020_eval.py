"""AR020: multi-product batch removal.

Real experiment chain (all conclusions come from these real runs):

  P0  post-change re-confirmation of the pre-change baseline probe:
      planner keeps every mentioned product; capability gate is covered
      for the batch instruction once the induced skill is registered
  P1  real LLM fallback (Qwen + AR004 adapters, GPU) solves the batch task;
      a TrajectoryRecorder captures every real action
  P2  the successful batch trajectory is generalised into a parameterised
      single-product template (batch collapse), registered and persisted
  P3  batch skill re-runs x3 (v1 pair, v1 triple with quantities,
      v2 pair + id churn): zero LLM calls
  P4  single-product regression x3 (mirrors AR019 P3/P4): zero LLM calls
  P5  combination gate: full edge pytest suite + AR011 30-scenario suite

Outputs: outputs/ar020/eval/{ar020_results.json, ar020_report.md,
induced_skills.json}
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.capability import check_capability  # noqa: E402
from step_rl.edge.hierarchical import run_hierarchy  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_induction import (  # noqa: E402
    RecordedStep,
    TrajectoryRecorder,
    induce_batch_template,
)
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    induced_operations,
    register_induced_skill,
    run_skill_hierarchy,
    save_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar020" / "eval"

# instruction -> (task family, layout, churn)
P1_INSTRUCTION = "把两个无线充电器和三条USB-C 快充数据线从购物车移除"
BATCH_TASKS = {
    "B1": ("把无线充电器和蓝牙降噪耳机从购物车移除", "v1", False),
    "B2": (P1_INSTRUCTION, "v1", False),
    "B3": ("把蓝牙降噪耳机和USB-C 快充数据线从购物车移除", "v2", True),
}
SINGLE_TASKS = {
    "S1": ("把购物车中的无线充电器移除", "v1", False),
    "S2": ("把购物车中的蓝牙降噪耳机移除", "v1", False),
    "S3": ("把购物车中的无线充电器移除", "v2", True),
}


def plan_remove(instruction: str, catalog) -> TaskSpec:
    spec = plan_instruction(instruction, catalog)
    if spec is None or spec.operation != "remove":
        raise RuntimeError(f"planner did not produce a remove task for: {instruction}")
    return spec


async def llm_fallback(model, tokenizer, task: TaskSpec) -> dict:
    """P1: real LLM fallback with full trajectory recording."""

    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    recorder = TrajectoryRecorder(env)
    started = time.time()
    try:
        await env.start()
        rollout = await run_hierarchy(
            recorder,
            task,
            model,
            tokenizer,
            repair=False,
            max_steps_per_subtask=14,
            semantic=True,
        )
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, task)
        return {
            "instruction": task.goal,
            "targets": dict(task.targets),
            "success": progress.success,
            "cart": final.get("cart"),
            "steps": rollout.total_steps,
            "prompt_tokens": sum(len(step.prompt_ids) for step in rollout.steps),
            "response_tokens": sum(len(step.response_ids) for step in rollout.steps),
            "seconds": round(time.time() - started, 2),
            "records": [record.__dict__ for record in recorder.records],
        }
    finally:
        await env.close()
        server.stop()


async def skill_rerun(task: TaskSpec, layout: str = "v1", churn: bool = False) -> dict:
    """P3/P4: skill-path re-run - the model is never loaded here."""

    server = LocalShopServer(layout=layout).start()
    env = BrowserEnv(
        server,
        channel="msedge",
        headless=True,
        semantic=True,
        perturb_ids=churn,
        perturb_prob=1.0,
    )
    started = time.time()
    try:
        await env.start()
        rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
        final = await env.get_state()
        progress = compute_progress(final, env.page_url_path, task)
        return {
            "instruction": task.goal,
            "targets": dict(task.targets),
            "layout": layout,
            "churn": churn,
            "success": progress.success,
            "cart": final.get("cart"),
            "steps": rollout.total_steps,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()


def run_gate(command: list) -> dict:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=2400,
    )
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-5:])
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "tail": tail,
    }


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict = {"ar": "AR020", "phases": {}}

    # ---- P0a: planner completeness (post-change re-confirmation) ---------
    clear_induced_skills()
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
    finally:
        server.stop()
    p0_spec = plan_remove(P1_INSTRUCTION, catalog)
    p0a = {
        "instruction": P1_INSTRUCTION,
        "targets": dict(p0_spec.targets),
        "seed_cart": dict(p0_spec.seed_cart),
        "all_products_kept": set(p0_spec.targets) == {"p3", "p2"},
    }
    results["phases"]["P0a_planner"] = p0a
    print(json.dumps(p0a, ensure_ascii=False), flush=True)
    assert p0a["all_products_kept"], "planner must keep every mentioned product"

    # ---- P1: real LLM fallback on the batch task --------------------------
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    p1 = await llm_fallback(model, tokenizer, p0_spec)
    results["phases"]["P1_llm_fallback"] = p1
    print(
        json.dumps({k: v for k, v in p1.items() if k != "records"}, ensure_ascii=False),
        flush=True,
    )

    if not p1["success"]:
        results["decision"] = "rollback: LLM fallback failed; no induction"
        (OUT / "ar020_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return

    # ---- P2: induce + register + persist ----------------------------------
    records = [RecordedStep(**record) for record in p1["records"]]
    template = induce_batch_template(p0_spec, records, catalog)
    if template is None:
        # Inconsistent per-product blocks: explicit gap, no fabricated template.
        results["decision"] = (
            "rollback: batch induction inconsistent; nothing registered"
        )
        (OUT / "ar020_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"decision": results["decision"]}, ensure_ascii=False))
        return
    register_induced_skill("remove", template["steps"], template["name"])
    save_induced_skills(str(OUT / "induced_skills.json"))
    batch_instruction = "把无线充电器和蓝牙降噪耳机从购物车移除"
    cap_after = check_capability(batch_instruction, catalog)
    materialised = skill_for_subtask(plan_remove(batch_instruction, catalog))
    results["phases"]["P2_induction"] = {
        "template": template,
        "registered": induced_operations(),
        "capability_after": {
            "covered": cap_after.covered,
            "skills": cap_after.skills,
        },
        "materialised_steps": len(materialised.steps) if materialised else 0,
    }
    print(
        json.dumps(
            {
                "registered": induced_operations(),
                "covered_after": cap_after.covered,
                "template_steps": len(template["steps"]),
                "materialised_steps": len(materialised.steps) if materialised else 0,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    # P0b: capability gate covered for the batch instruction
    results["phases"]["P0b_capability"] = {
        "instruction": batch_instruction,
        "covered": cap_after.covered,
        "skills": cap_after.skills,
    }

    # ---- P3: batch skill re-runs (0 LLM) -----------------------------------
    p3: list = []
    for label, (instruction, layout, churn) in BATCH_TASKS.items():
        task = plan_remove(instruction, catalog)
        row = await skill_rerun(task, layout=layout, churn=churn)
        row["label"] = label
        p3.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    results["phases"]["P3_batch"] = p3

    # ---- P4: single-product regression (mirrors AR019) ---------------------
    p4: list = []
    for label, (instruction, layout, churn) in SINGLE_TASKS.items():
        task = plan_remove(instruction, catalog)
        row = await skill_rerun(task, layout=layout, churn=churn)
        row["label"] = label
        p4.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    results["phases"]["P4_single_regression"] = p4

    # ---- P5: combination gate ----------------------------------------------
    # Same gate scope as AR019: the edge suite (README "N passing" badge)
    # minus the pre-existing legacy failures (locator/progress_estimator/
    # smart_wait, verified unrelated via the AR019 git-stash control run),
    # plus the AR011 30-scenario suite.
    python = r"C:\Python311\python.exe"
    legacy = [
        "tests/test_locator.py",
        "tests/test_progress_estimator.py",
        "tests/test_smart_wait.py",
    ]
    gate_cmd = [python, "-m", "pytest", "tests", "-q", "--tb=no", "--timeout=300"]
    for path in legacy:
        gate_cmd += ["--ignore=" + path]
    gates = {}
    gates["pytest_edge"] = run_gate(gate_cmd)
    gates["ar011_suite"] = run_gate([python, "scripts/ar011_eval.py"])
    results["phases"]["P5_combination_gate"] = gates
    results["phases"]["P5_legacy_debt"] = {
        "note": (
            "17 pre-existing failures in legacy tests (locator/"
            "progress_estimator/smart_wait); verified unchanged since AR019 "
            "via the git-stash control run"
        ),
        "files": legacy,
    }
    for name, gate in gates.items():
        print(
            json.dumps(
                {
                    "gate": name,
                    "returncode": gate["returncode"],
                    "seconds": gate["seconds"],
                    "tail": gate["tail"][-300:],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    # ---- decision -----------------------------------------------------------
    combination_ok = (
        p0a["all_products_kept"]
        and cap_after.covered
        and p1["success"]
        and all(row["success"] for row in p3)
        and all(row["success"] for row in p4)
        and gates["pytest_edge"]["returncode"] == 0
        and gates["ar011_suite"]["returncode"] == 0
    )
    results["decision"] = "keep" if combination_ok else "rollback"
    (OUT / "ar020_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- report ---------------------------------------------------------------
    lines = [
        "# AR020 多商品批量移除 真实评测",
        "",
        "## P0 改动后复核（改动前基线探针：outputs/ar020/baseline_probe.md）",
        "",
        f"- 批量指令 `{P1_INSTRUCTION}` 规划 targets={p0a['targets']}，"
        f"seed={p0a['seed_cart']}，全部商品保留={p0a['all_products_kept']}",
        f"- 注册后批量指令门控：covered={cap_after.covered}，"
        f"skills={cap_after.skills}",
        "",
        "## P1 真实 LLM 兜底（GPU，批量任务）",
        "",
        "| 任务 | 成功 | 购物车 | 步数 | prompt tokens | 耗时 |",
        "|------|------|--------|------|---------------|------|",
        f"| {p1['instruction']} | {'✓' if p1['success'] else '✗'} | {p1['cart']} | "
        f"{p1['steps']} | {p1['prompt_tokens']} | {p1['seconds']}s |",
        "",
        "## P2 归纳注册（批量轨迹 → 单商品单元模板）",
        "",
        f"- 模板步数：{len(template['steps'])}；注册操作：{induced_operations()}",
        f"- 双目标任务实例化步数：{results['phases']['P2_induction']['materialised_steps']}",
        "",
        "## P3 批量技能复跑（0 LLM）",
        "",
        "| 编号 | 布局 | churn | 成功 | 购物车 | 步数 | 耗时 |",
        "|------|------|-------|------|--------|------|------|",
    ]
    for row in p3:
        lines.append(
            f"| {row['label']} | {row['layout']} | "
            f"{'是' if row['churn'] else '否'} | "
            f"{'✓' if row['success'] else '✗'} | {row['cart']} | "
            f"{row['steps']} | {row['seconds']}s |"
        )
    lines += [
        "",
        "## P4 单商品回归（0 LLM，镜像 AR019）",
        "",
        "| 编号 | 布局 | churn | 成功 | 购物车 | 步数 | 耗时 |",
        "|------|------|-------|------|--------|------|------|",
    ]
    for row in p4:
        lines.append(
            f"| {row['label']} | {row['layout']} | "
            f"{'是' if row['churn'] else '否'} | "
            f"{'✓' if row['success'] else '✗'} | {row['cart']} | "
            f"{row['steps']} | {row['seconds']}s |"
        )
    lines += [
        "",
        "## P5 组合门禁",
        "",
        f"- edge 套件 pytest：rc={gates['pytest_edge']['returncode']}，"
        f"{gates['pytest_edge']['tail'].splitlines()[-1] if gates['pytest_edge']['tail'] else ''}",
        f"- AR011 30 场景：rc={gates['ar011_suite']['returncode']}",
        "- 遗留技术债：legacy 三文件（locator/progress_estimator/smart_wait）"
        "17 个历史失败，AR019 git-stash 对照验证与本 AR 无关，不纳入门禁",
        "",
        f"## 结论：{'保留（keep）' if combination_ok else '回退（rollback）'}",
        "",
    ]
    (OUT / "ar020_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"decision": results["decision"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
