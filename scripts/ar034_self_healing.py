"""AR034: real Qwen self-healing runtime experiment (baseline vs auto-repair)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.modeling import load_multi_adapter, resolve_model_path, set_seed  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import clear_induced_skills, save_induced_skills  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402

OUT = ROOT / "outputs" / "ar034"
GIF = ROOT / "docs" / "images" / "ar034_demo.gif"
ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
INSTRUCTION = "把购物车中的无线充电器移除"


async def run_once(env, model, tokenizer, enable, label, learning_path):
    task = TaskSpec(
        task_id=label,
        level=3,
        goal=INSTRUCTION,
        search_query="",
        targets={"p3": 0},
        operation="remove",
        seed_cart={"p3": 1},
        start_path="/cart",
    )
    await env.reset(task)
    started = time.time()
    result = await run_task(
        env,
        INSTRUCTION,
        model,
        tokenizer,
        enable_self_healing=enable,
        learning_path=learning_path if enable else "",
    )
    state = await env.get_state()
    png = await env.screenshot()
    steps = result.get("steps", [])
    return {
        "label": label,
        "self_healing": enable,
        "success": bool(result.get("success")),
        "fallback": bool(result.get("fallback", False)),
        "policy_steps": sum(1 for step in steps if step.source == "policy"),
        "skill_steps": sum(1 for step in steps if step.source == "skill"),
        "prompt_tokens": sum(len(step.prompt_ids) for step in steps),
        "cart": state.get("cart", {}),
        "seconds": round(time.time() - started, 2),
        "healed_skill": result.get("healed_skill", ""),
        "_png": png,
    }


def caption(image: Image.Image, text: str) -> Image.Image:
    width = 480
    ratio = width / image.width
    resized = image.resize((width, int(image.height * ratio)), Image.LANCZOS)
    canvas = Image.new("RGB", (width, resized.height + 40), (10, 15, 30))
    canvas.paste(resized, (0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, resized.height + 8), text, fill=(235, 241, 255), font=font)
    return canvas.convert("P", palette=Image.ADAPTIVE, colors=48)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    rows = []
    frames = []
    try:
        await env.start()
        clear_induced_skills()
        for index in (1, 2):
            row = await run_once(env, model, tokenizer, False, f"baseline_{index}", "")
            rows.append(row)
            frames.append(caption(Image.open(__import__("io").BytesIO(row["_png"])),
                                  f"baseline #{index}: LLM={row['policy_steps']} steps, tokens={row['prompt_tokens']}"))
        clear_induced_skills()
        learning_path = str(OUT / "induced_skills.json")
        for index in (1, 2):
            row = await run_once(env, model, tokenizer, True, f"self_heal_{index}", learning_path)
            rows.append(row)
            label = "self-heal #1: LLM + auto-register" if index == 1 else "self-heal #2: 0 LLM skill reuse"
            frames.append(caption(Image.open(__import__("io").BytesIO(row["_png"])),
                                  f"{label}; policy={row['policy_steps']} skill={row['skill_steps']}"))
        save_induced_skills(learning_path)
    finally:
        await env.close()
        server.stop()
    for row in rows:
        row.pop("_png", None)
    payload = {"ar": "AR034", "rows": rows}
    (OUT / "eval").mkdir(parents=True, exist_ok=True)
    (OUT / "eval" / "ar034_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    frames[0].save(GIF, save_all=True, append_images=frames[1:], duration=900, loop=0, optimize=True)
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    assert rows[0]["policy_steps"] > 0 and rows[1]["policy_steps"] > 0
    assert rows[2]["policy_steps"] > 0 and rows[3]["policy_steps"] == 0


if __name__ == "__main__":
    asyncio.run(main())
