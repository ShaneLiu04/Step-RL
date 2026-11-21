"""Record a real-Edge GIF demo for AR028 (cart -> checkout -> promo)."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402

OUT = ROOT / "outputs" / "ar028" / "demo"
GIF = ROOT / "docs" / "images" / "ar028_demo.gif"
FONT = Path("C:/Windows/Fonts/msyh.ttc")


def compose(frames: list[Image.Image], captions: list[str]) -> Image.Image:
    width = 480
    scaled = []
    for frame in frames:
        ratio = width / frame.width
        image = frame.resize((width, int(frame.height * ratio)), Image.LANCZOS)
        canvas = Image.new("RGB", (width, image.height + 44), (10, 15, 30))
        canvas.paste(image, (0, 0))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype(str(FONT), 18)
        except Exception:
            font = ImageFont.load_default()
        draw.text(
            (10, image.height + 10),
            captions[len(scaled) % len(captions)],
            fill=(235, 241, 255),
            font=font,
        )
        scaled.append(canvas.convert("P", palette=Image.ADAPTIVE, colors=48))
    return scaled


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    instruction = "把购物车里的所有商品数量都加倍，并使用满400减50优惠结算"
    try:
        await env.start()
        task = TaskSpec(
            task_id="demo",
            level=5,
            goal=instruction,
            search_query="",
            targets={},
            start_path="/cart",
            seed_cart={"p3": 1, "p4": 1},
        )
        await env.reset(task)
        raw = []
        raw.append(Image.open(io.BytesIO(await env._page.screenshot())))
        stop = asyncio.Event()

        async def capture():
            while not stop.is_set():
                try:
                    raw.append(Image.open(io.BytesIO(await env._page.screenshot())))
                except Exception:
                    pass
                await asyncio.sleep(0.25)

        capture_task = asyncio.create_task(capture())
        result = await run_task(env, instruction, None, None)
        stop.set()
        await capture_task
        raw.append(Image.open(io.BytesIO(await env._page.screenshot())))
        state = await env.get_state()
        order = state.get("order") or {}
        print({"success": result.get("success"), "order": order}, flush=True)
    finally:
        await env.close()
        server.stop()

    captions = [
        "1) 购物车：p3×1, p4×1",
        "2) 真实 Edge 事务执行",
        "3) 数量加倍 + 满400减50",
        "4) 结算中（真实表单/服务端）",
        "5) 订单成功：total ¥1196 / paid ¥1146",
    ]
    selected = (
        raw[:1] + raw[max(1, len(raw) // 3) : max(2, 2 * len(raw) // 3)] + raw[-2:]
    )
    # keep 5-7 representative real frames; deduplicate identical screenshots
    unique = []
    seen = set()
    for image in selected:
        digest = image.resize((32, 32)).tobytes()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(image)
    if len(unique) < 3:
        unique = raw[:1] + raw[-1:]
    frames = compose(unique, captions)
    frames[0].save(
        GIF,
        save_all=True,
        append_images=frames[1:],
        duration=900,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print({"gif": str(GIF), "bytes": GIF.stat().st_size, "frames": len(frames)})


if __name__ == "__main__":
    asyncio.run(main())
