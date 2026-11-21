"""AR033 hybrid system validation (real CPU/GPU/local/remote evidence)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.console.app import SessionManager  # noqa: E402
from step_rl.edge.adapters.evidence import EvidenceWriter  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.system import HybridSystem  # noqa: E402

OUT = ROOT / "outputs" / "ar033" / "eval"
ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
LOCAL_CASES = [
    ("买两件无线充电器", "/", {}),
    ("买一件蓝牙降噪耳机并结算", "/", {}),
    ("买两件USB-C数据线并结算", "/", {}),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    system = HybridSystem()
    run_id = "ar033_system"
    writer = EvidenceWriter(OUT, run_id, "local")
    results = {"ar": "AR033", "run_id": run_id, "local_cpu": [], "gpu_fallback": {}, "console": {}, "remote": []}

    for instruction, start_path, seed in LOCAL_CASES:
        row = await system.run_local(
            instruction, start_path=start_path, seed_cart=seed, evidence=writer
        )
        row["mode"] = "deterministic_cpu_0_llm"
        results["local_cpu"].append(row)

    manager = SessionManager()
    session = manager.create("local", "买两件无线充电器")
    await session._task
    results["console"] = {
        "status": session.status,
        "success": bool(session.result.get("success")),
        "steps": session.result.get("steps"),
        "screenshot": bool(session.screenshot_b64),
        "events": len(session.events),
        "audit_dir": str(session.audit_dir),
    }

    for site, query in (
        ("jd", "无线充电器"),
        ("taobao", "无线充电器"),
        ("amazon", "usb c cable"),
    ):
        results["remote"].append(await system.run_remote(site, query))

    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    gpu_started = time.time()
    results["gpu_fallback"] = await system.run_local(
        "把购物车中的无线充电器移除",
        start_path="/cart",
        seed_cart={"p3": 1},
        model=model,
        tokenizer=tokenizer,
    )
    results["gpu_fallback"]["mode"] = "gpu_llm_fallback"
    results["gpu_fallback"]["wall_seconds"] = round(time.time() - gpu_started, 2)

    (OUT / "ar033_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR033 混合系统级验证",
        "",
        "## CPU 确定性路径（0 LLM）",
        "",
        "| 指令 | 成功 | 步数 | 秒 |",
        "|------|------|------|----|",
    ]
    for row in results["local_cpu"]:
        lines.append(
            f"| {row['instruction']} | {'✓' if row['success'] else '✗'} | {row['steps']} | {row['seconds']} |"
        )
    gpu = results["gpu_fallback"]
    lines += [
        "",
        "## GPU 端侧 LLM 兜底",
        "",
        f"- 成功：{gpu.get('success')}；fallback={gpu.get('fallback')}；"
        f"policy_steps={gpu.get('policy_steps')}；prompt_tokens={gpu.get('prompt_tokens')}；"
        f"wall={gpu.get('wall_seconds')}s；cart={gpu.get('cart')}",
        "",
        "## Console",
        "",
        json.dumps(results["console"], ensure_ascii=False),
        "",
        "## 远程只读（真实状态，不伪造）",
        "",
        "| 站点 | ok | title | blocked | item_links |",
        "|------|----|-------|---------|------------|",
    ]
    for row in results["remote"]:
        lines.append(
            f"| {row['site']} | {row['ok']} | {row.get('title','')[:30]} | "
            f"{row.get('blocked','')} | {row.get('item_links','-')} |"
        )
    (OUT / "ar033_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
