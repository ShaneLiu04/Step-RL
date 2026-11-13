"""Generate the Step-RL v3.0 README cover banner.

Outputs a 1600x720 PNG (rendered at 2x and downsampled) to
``docs/images/cover.png``. Pure Pillow + NumPy, no external assets.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Canvas / scale
# ---------------------------------------------------------------------------
S = 2
W, H = 1600, 720
CW, CH = W * S, H * S

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "cover.jpg"
OUT.parent.mkdir(parents=True, exist_ok=True)

FONT_DIR = Path("C:/Windows/Fonts")
F_EN = FONT_DIR / "segoeuib.ttf"
F_EN_SEMI = FONT_DIR / "seguisb.ttf"
F_EN_LIGHT = FONT_DIR / "segoeuil.ttf"
F_CN = FONT_DIR / "msyhbd.ttc"
F_CN_REG = FONT_DIR / "msyh.ttc"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size * S)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------
def build_background() -> Image.Image:
    y, x = np.mgrid[0:CH, 0:CW].astype(np.float32)

    # Base vertical gradient (top -> bottom)
    t = (y / CH)[..., None]
    top = np.array([7, 11, 30], dtype=np.float32)
    mid = np.array([15, 24, 56], dtype=np.float32)
    bot = np.array([8, 13, 34], dtype=np.float32)
    upper = top + (mid - top) * np.clip(t * 2, 0, 1)
    lower = mid + (bot - mid) * np.clip((t - 0.5) * 2, 0, 1)
    base = np.where(t < 0.5, upper, lower)

    img = np.repeat(base, 1, axis=0)

    # Radial glows: (cx, cy, radius, rgb, strength)
    glows = [
        (1180 * S, 230 * S, 560 * S, (37, 99, 235), 0.62),
        (1420 * S, 600 * S, 470 * S, (124, 58, 237), 0.50),
        (300 * S, 110 * S, 430 * S, (6, 182, 212), 0.20),
        (760 * S, 760 * S, 520 * S, (236, 72, 153), 0.10),
    ]
    for cx, cy, r, rgb, strength in glows:
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        falloff = np.clip(1 - d, 0, 1) ** 2.4
        img += falloff[..., None] * np.array(rgb, dtype=np.float32) * strength

    # Faint grid
    cell = 40 * S
    grid = ((x % cell < 1.5) | (y % cell < 1.5)).astype(np.float32)
    img += grid[..., None] * np.array([120, 150, 220], dtype=np.float32) * 0.055

    # Vignette
    nx = (x - CW / 2) / (CW / 2)
    ny = (y - CH / 2) / (CH / 2)
    vig = np.clip(1 - 0.45 * (nx**2 + ny**2), 0, 1)
    img *= vig[..., None]

    img = np.clip(img, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = [v * S for v in box]
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius * S,
        fill=fill,
        outline=outline,
        width=int(width * S),
    )


def text(draw, xy, s, fnt, fill, anchor="la", shadow=None, shadow_off=(0, 4)):
    if shadow:
        sx, sy = shadow_off
        draw.text(
            (xy[0] * S + sx * S, xy[1] * S + sy * S),
            s,
            font=fnt,
            fill=shadow,
            anchor=anchor,
        )
    draw.text((xy[0] * S, xy[1] * S), s, font=fnt, fill=fill, anchor=anchor)


def measure(fnt, s) -> tuple[int, int]:
    b = fnt.getbbox(s)
    return (b[2] - b[0]) / S, (b[3] - b[1]) / S


def gradient_text(canvas, xy, s, fnt, colors, anchor="la"):
    """Draw text filled with a horizontal gradient, with soft shadow."""
    b = fnt.getbbox(s)
    tw, th = b[2] - b[0], b[3] - b[1]
    pad = 8 * S
    mask = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(mask).text((pad - b[0], pad - b[1]), s, font=fnt, fill=255)

    grad = Image.new("RGB", mask.size, colors[0])
    gd = ImageDraw.Draw(grad)
    seg = mask.size[0] / (len(colors) - 1)
    for i in range(mask.size[0]):
        pos = i / seg
        i0 = min(int(pos), len(colors) - 2)
        f = pos - i0
        c0 = np.array(colors[i0], dtype=np.float32)
        c1 = np.array(colors[i0 + 1], dtype=np.float32)
        c = (c0 + (c1 - c0) * f).astype(int)
        gd.line([(i, 0), (i, mask.size[1])], fill=tuple(c))

    # Shadow layer
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    smask = Image.new("L", canvas.size, 0)
    # approximate anchor placement
    ax = xy[0] * S
    ay = xy[1] * S
    if anchor == "la":
        ox, oy = ax - pad, ay - pad
    elif anchor == "ma":
        ox, oy = ax - (tw + pad * 2) / 2, ay - pad
    else:
        ox, oy = ax - pad, ay - pad
    smask.paste(mask, (int(ox), int(oy) + 5 * S))
    smask = smask.filter(ImageFilter.GaussianBlur(7 * S))
    shadow.putalpha(smask.point(lambda v: int(v * 0.55)))

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(grad, (int(ox), int(oy)), mask)
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(layer)


# ---------------------------------------------------------------------------
# Right-hand agent loop card
# ---------------------------------------------------------------------------
def draw_agent_loop(canvas: Image.Image):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    card = (944, 92, 1524, 656)
    rounded_rect(
        d, card, 34, fill=(255, 255, 255, 12), outline=(255, 255, 255, 42), width=1.4
    )
    # inner subtle top highlight
    rounded_rect(
        d,
        (card[0] + 1, card[1] + 1, card[2] - 1, card[1] + 90),
        33,
        fill=(255, 255, 255, 8),
    )

    text(
        d,
        (984, 138),
        "A G E N T   L O O P",
        font(F_EN_SEMI, 17),
        (128, 152, 196, 235),
        anchor="lm",
    )
    rounded_rect(
        d,
        (1372, 124, 1484, 152),
        14,
        fill=(34, 197, 94, 28),
        outline=(74, 222, 128, 110),
        width=1,
    )
    text(
        d, (1428, 137), "ONLINE", font(F_EN_SEMI, 13), (134, 239, 172, 255), anchor="mm"
    )

    cx, cy, radius = 1234, 376, 146
    node_positions = {
        "Observe": (cx, cy - radius),
        "Act": (cx + radius, cy),
        "Verify": (cx, cy + radius),
        "Reward": (cx - radius, cy),
    }
    node_style = {
        "Observe": ((34, 211, 238), (8, 145, 178)),
        "Act": ((96, 165, 250), (37, 99, 235)),
        "Verify": ((192, 132, 252), (124, 58, 237)),
        "Reward": ((244, 114, 182), (219, 39, 119)),
    }

    # Dashed ring
    import math

    segments = 72
    for i in range(segments):
        if i % 3 == 2:
            continue
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 0.55) / segments
        x0 = (cx + radius * math.cos(a0)) * S
        y0 = (cy + radius * math.sin(a0)) * S
        x1 = (cx + radius * math.cos(a1)) * S
        y1 = (cy + radius * math.sin(a1)) * S
        d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 55), width=int(1.4 * S))

    # Directional chevrons along the ring (clockwise)
    for ang in (315, 45, 135, 225):
        a = math.radians(ang)
        px, py = cx + radius * math.cos(a), cy + radius * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)
        nx, ny = -ty, tx
        tip = (px + tx * 11, py + ty * 11)
        b1 = (px - tx * 5 + nx * 7, py - ty * 5 + ny * 7)
        b2 = (px - tx * 5 - nx * 7, py - ty * 5 - ny * 7)
        d.polygon(
            [(tip[0] * S, tip[1] * S), (b1[0] * S, b1[1] * S), (b2[0] * S, b2[1] * S)],
            fill=(170, 195, 255, 170),
        )

    # Center core
    rounded_rect(
        d,
        (cx - 118, cy - 52, cx + 118, cy + 52),
        22,
        fill=(255, 255, 255, 18),
        outline=(255, 255, 255, 65),
        width=1.3,
    )
    text(
        d,
        (cx, cy - 12),
        "Policy Core",
        font(F_EN_SEMI, 20),
        (236, 242, 255, 255),
        anchor="mm",
    )
    text(
        d,
        (cx, cy + 18),
        "Qwen + LoRA",
        font(F_EN_LIGHT, 14),
        (158, 176, 212, 255),
        anchor="mm",
    )

    # Nodes
    for name, (nx, ny) in node_positions.items():
        c_hi, c_lo = node_style[name]
        for r, alpha in ((44, 26), (36, 60), (30, 255)):
            col = tuple(int(v * 1.0) for v in c_lo) + (alpha,)
            d.ellipse(
                [(nx - r) * S, (ny - r) * S, (nx + r) * S, (ny + r) * S],
                fill=col if alpha < 255 else tuple(c_lo) + (255,),
            )
        d.ellipse(
            [(nx - 16) * S, (ny - 16) * S, (nx + 16) * S, (ny + 16) * S],
            fill=tuple(c_hi) + (255,),
        )

    label_pos = {
        "Observe": (cx, cy - radius - 64, "mb"),
        "Act": (cx + radius + 58, cy, "lm"),
        "Verify": (cx, cy + radius + 40, "mt"),
        "Reward": (cx - radius - 58, cy, "rm"),
    }
    for name, (lx, ly, anchor) in label_pos.items():
        text(
            d, (lx, ly), name, font(F_EN_SEMI, 19), (222, 232, 252, 255), anchor=anchor
        )

    # Bottom badges
    badges = [("TFR", "retry"), ("SAGA", "compensation")]
    bx = 984
    for label, value in badges:
        w = 128
        rounded_rect(
            d,
            (bx, 588, bx + w, 636),
            16,
            fill=(255, 255, 255, 14),
            outline=(255, 255, 255, 48),
            width=1,
        )
        text(
            d,
            (bx + w / 2, 604),
            label,
            font(F_EN_SEMI, 15),
            (226, 236, 255, 255),
            anchor="mm",
        )
        text(
            d,
            (bx + w / 2, 624),
            value,
            font(F_EN_LIGHT, 12),
            (150, 170, 208, 255),
            anchor="mm",
        )
        bx += w + 18

    # Floating accents
    for fx, fy, fr, col in [
        (1000, 470, 3, (34, 211, 238)),
        (1470, 300, 2.5, (192, 132, 252)),
        (1450, 468, 2, (244, 114, 182)),
    ]:
        d.ellipse(
            [(fx - fr) * S, (fy - fr) * S, (fx + fr) * S, (fy + fr) * S],
            fill=tuple(col) + (160,),
        )

    canvas.alpha_composite(layer)


# ---------------------------------------------------------------------------
# Left content
# ---------------------------------------------------------------------------
def draw_left(canvas: Image.Image):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    # Top pill
    pill_txt = "REAL HTTP SHOP   ·   REAL EDGE   ·   SKILL PRIORITY"
    f_pill = font(F_EN_SEMI, 15)
    pw, _ = measure(f_pill, pill_txt)
    rounded_rect(
        d,
        (88, 66, 88 + pw + 52, 106),
        20,
        fill=(255, 255, 255, 16),
        outline=(120, 160, 235, 80),
        width=1,
    )
    d.ellipse([107 * S, 83 * S, 115 * S, 91 * S], fill=(74, 222, 128, 255))
    text(d, (126, 86), pill_txt, f_pill, (176, 194, 228, 255), anchor="lm")

    # Title
    f_title = font(F_EN, 148)
    gradient_text(
        canvas,
        (86, 136),
        "Step-RL",
        f_title,
        [(125, 211, 252), (129, 140, 248), (232, 121, 249)],
    )

    # v3.0 badge
    title_w = measure(f_title, "Step-RL")[0]
    bx = 86 + title_w + 28
    by = 196
    rounded_rect(
        d,
        (bx, by, bx + 122, by + 54),
        18,
        fill=(79, 70, 229, 60),
        outline=(165, 180, 252, 150),
        width=1.4,
    )
    text(
        d,
        (bx + 61, by + 28),
        "v4.10",
        font(F_EN_SEMI, 26),
        (224, 231, 255, 255),
        anchor="mm",
    )

    # Subtitle
    text(
        d,
        (88, 316),
        "技能成功率统计与优先级 · 端侧分层强化学习",
        font(F_CN, 35),
        (226, 234, 252, 255),
        anchor="la",
        shadow=(0, 0, 0, 120),
        shadow_off=(0, 3),
    )

    # Divider
    line = Image.new("RGBA", (CW, 2 * S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    for i in range(900 * S):
        alpha = int(150 * (1 - i / (900 * S)))
        ld.line([(i, 0), (i, 2 * S)], fill=(120, 150, 210, alpha))
    canvas.alpha_composite(line, (88 * S, 384 * S))

    # Problem statement
    text(
        d,
        (88, 410),
        "目标：失败留痕、统计下降即让位、闭环重归纳",
        font(F_CN_REG, 21),
        (148, 168, 204, 255),
        anchor="la",
    )

    # Feature chips
    chips = [
        ("成功率统计", (34, 211, 238)),
        ("失败让位", (96, 165, 250)),
        ("淘汰重归纳", (167, 139, 250)),
        ("跨布局迁移", (244, 114, 182)),
        ("语义动作", (74, 222, 128)),
    ]
    f_chip = font(F_CN_REG, 17)
    cxp = 88
    for label, col in chips:
        tw, _ = measure(f_chip, label)
        w = tw + 38
        rounded_rect(
            d,
            (cxp, 458, cxp + w, 500),
            21,
            fill=tuple(col) + (24,),
            outline=tuple(col) + (110,),
            width=1,
        )
        d.ellipse(
            [(cxp + 16) * S, 476 * S, (cxp + 22) * S, 482 * S], fill=tuple(col) + (255,)
        )
        text(d, (cxp + 29, 470), label, f_chip, (214, 226, 246, 255), anchor="la")
        cxp += w + 12

    # Metrics
    metrics = [
        ("0/1", "失效技能淘汰", (125, 211, 252)),
        ("0", "LLM 让位复用", (167, 139, 250)),
        ("30/30", "统一场景", (244, 114, 182)),
        ("179", "真实测试", (74, 222, 128)),
    ]
    mx = 88
    my = 556
    col_w = 198
    for i, (value, label, col) in enumerate(metrics):
        if i > 0:
            d.line(
                [(mx - 18) * S, my * S, (mx - 18) * S, (my + 82) * S],
                fill=(255, 255, 255, 34),
                width=int(1 * S),
            )
        text(
            d,
            (mx, my + 4),
            value,
            font(F_EN_SEMI, 42),
            tuple(col) + (255,),
            anchor="la",
        )
        text(
            d,
            (mx + 1, my + 64),
            label,
            font(F_CN_REG, 18),
            (134, 154, 192, 255),
            anchor="la",
        )
        mx += col_w

    # Footer
    text(
        d,
        (88, 672),
        "gitee.com/liu-xingyan04/step-rl",
        font(F_EN_LIGHT, 19),
        (118, 136, 176, 255),
        anchor="lm",
    )
    text(
        d,
        (760, 672),
        "Step-RL  ·  Long-Horizon Agent RL",
        font(F_EN_LIGHT, 17),
        (96, 112, 150, 255),
        anchor="lm",
    )

    canvas.alpha_composite(layer)


def main():
    canvas = build_background()

    # Soft top-left shine (under the content layers)
    shine = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shine)
    sd.ellipse(
        [-300 * S, -420 * S, 1100 * S, 160 * S],
        fill=(120, 170, 255, 26),
    )
    shine = shine.filter(ImageFilter.GaussianBlur(90 * S))
    canvas.alpha_composite(shine)

    draw_agent_loop(canvas)
    draw_left(canvas)

    full = canvas.convert("RGB").resize((W, H), Image.LANCZOS)
    full_dir = ROOT / "outputs" / "ar001"
    full_dir.mkdir(parents=True, exist_ok=True)
    full.save(full_dir / "cover_full.png", "PNG", optimize=True)
    # Repository asset: keep the push under the corporate proxy limit (~100KB).
    out = full.resize((1100, 495), Image.LANCZOS)
    out.save(OUT, "JPEG", quality=84, optimize=True, subsampling=0)
    print(f"[OK] {OUT}  ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    main()
