"""Generate the Step-RL v3.5 README cover banner.

The banner is rendered at 2x and downsampled to 1920x960.  It is a pure
Pillow + NumPy composition: no external assets, only system fonts.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Canvas / scale
# ---------------------------------------------------------------------------
S = 2
W, H = 1920, 960
CW, CH = W * S, H * S

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "cover.jpg"

FONT_DIR = Path("C:/Windows/Fonts")


def first_font(*names: str) -> str:
    for name in names:
        p = FONT_DIR / name
        if p.exists():
            return str(p)
    return "arial.ttf"


F_BOLD = first_font("segoeuib.ttf", "arialbd.ttf")
F_SEMI = first_font("seguisb.ttf", "arialbd.ttf")
F_LIGHT = first_font("segoeuil.ttf", "arial.ttf")
F_CN_BOLD = first_font("msyhbd.ttc", "simhei.ttf")
F_CN = first_font("msyh.ttc", "simhei.ttf")
F_MONO = first_font("consola.ttf", "CascadiaMono.ttf", "arial.ttf")
F_MONO_BOLD = first_font("consolab.ttf", "CascadiaMono.ttf", "arialbd.ttf")

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size * S)
    return _font_cache[key]


def measure(fnt: ImageFont.FreeTypeFont, s: str) -> tuple[float, float]:
    b = fnt.getbbox(s)
    return (b[2] - b[0]) / S, (b[3] - b[1]) / S


# ---------------------------------------------------------------------------
# Colour / gradient helpers
# ---------------------------------------------------------------------------
def h_gradient(
    size: tuple[int, int], colors: list[tuple[int, int, int]]
) -> Image.Image:
    w, h = size
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
    stops = np.linspace(0.0, 1.0, len(colors), dtype=np.float32)
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for c in range(3):
        vals = np.interp(xs, stops, [col[c] for col in colors]).astype(np.uint8)
        arr[:, :, c] = vals[None, :]
    return Image.fromarray(arr, "RGB")


def rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return tuple(color) + (alpha,)


def rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = [v * S for v in box]
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius * S,
        fill=fill,
        outline=outline,
        width=max(1, int(width * S)),
    )


def panel(
    canvas: Image.Image,
    box: tuple[float, float, float, float],
    radius: float,
    fill: tuple[int, int, int, int],
    border_colors: list[tuple[int, int, int]],
    border_alpha: int = 90,
    border_w: float = 1.2,
    highlight: bool = True,
):
    x0, y0, x1, y1 = [int(v * S) for v in box]
    w, h = x1 - x0, y1 - y0

    grad = h_gradient((w, h), border_colors).convert("RGBA")
    grad.putalpha(border_alpha)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=radius * S, fill=255
    )
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    border.paste(grad, (0, 0), mask)

    bw = max(1, int(border_w * S))
    inner = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner).rounded_rectangle(
        (bw, bw, w - bw, h - bw), radius=max(1, radius * S - bw), fill=255
    )
    alpha = border.getchannel("A")
    alpha = Image.composite(Image.new("L", (w, h), 0), alpha, inner)
    border.putalpha(alpha)

    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.rounded_rectangle(
        (bw, bw, w - bw, h - bw),
        radius=max(1, radius * S - bw),
        fill=fill,
    )
    if highlight:
        gloss = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gloss)
        gd.rounded_rectangle(
            (bw, bw, w - bw, int(h * 0.42)),
            radius=max(1, radius * S - bw),
            fill=(255, 255, 255, 7),
        )
        body.alpha_composite(gloss)
    border.alpha_composite(body)
    canvas.alpha_composite(border, (x0, y0))


def text(
    draw,
    xy,
    s,
    fnt,
    fill,
    anchor="la",
    shadow=None,
    shadow_off=(0, 3),
):
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


def gradient_text(
    canvas,
    xy,
    s,
    fnt,
    colors,
    anchor="la",
    glow=None,
    glow_alpha=90,
    glow_blur=16,
):
    b = fnt.getbbox(s)
    tw, th = b[2] - b[0], b[3] - b[1]
    pad = int(70 * S)
    mask = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(mask).text((pad - b[0], pad - b[1]), s, font=fnt, fill=255)

    ax, ay = xy[0] * S, xy[1] * S
    if anchor == "la":
        ox, oy = ax - pad, ay - pad
    elif anchor == "ma":
        ox, oy = ax - tw / 2 - pad, ay - pad
    elif anchor == "mm":
        ox, oy = ax - tw / 2 - pad, ay - th / 2 - pad
    else:
        ox, oy = ax - pad, ay - pad

    if glow:
        gm = mask.filter(ImageFilter.GaussianBlur(glow_blur * S))
        glow_img = Image.new("RGBA", gm.size, rgba(glow, 0))
        glow_img.putalpha(gm.point(lambda v: int(v * glow_alpha / 255)))
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.alpha_composite(glow_img, (int(ox), int(oy)))
        canvas.alpha_composite(layer)

    grad = h_gradient(mask.size, colors).convert("RGBA")
    grad.putalpha(mask)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.alpha_composite(grad, (int(ox), int(oy)))
    canvas.alpha_composite(layer)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------
def build_background() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)

    t = (y / H)[..., None]
    top = np.array([4, 9, 23], dtype=np.float32)
    mid = np.array([9, 19, 45], dtype=np.float32)
    bot = np.array([5, 9, 24], dtype=np.float32)
    upper = top + (mid - top) * np.clip(t * 2, 0, 1)
    lower = mid + (bot - mid) * np.clip((t - 0.5) * 2, 0, 1)
    base = np.where(t < 0.5, upper, lower)

    img = np.repeat(base, 1, axis=0)

    glows = [
        (240, 40, 620, (34, 211, 238), 0.16),
        (1450, 80, 720, (37, 99, 235), 0.38),
        (1840, 820, 640, (124, 58, 237), 0.28),
        (780, 980, 700, (236, 72, 153), 0.08),
        (360, 900, 520, (6, 182, 212), 0.08),
    ]
    for cx, cy, r, rgb, strength in glows:
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        falloff = np.clip(1 - d, 0, 1) ** 2.2
        img += falloff[..., None] * np.array(rgb, dtype=np.float32) * strength

    nx = (x - W / 2) / (W / 2)
    ny = (y - H / 2) / (H / 2)
    vig = np.clip(1 - 0.42 * (nx**2 + ny**2), 0, 1)
    img *= vig[..., None]

    img = np.clip(img, 0, 255).astype(np.uint8)
    canvas = Image.fromarray(img, "RGB").resize((CW, CH), Image.LANCZOS)
    canvas = canvas.convert("RGBA")

    d = ImageDraw.Draw(canvas, "RGBA")

    # Dot grid
    step = 38 * S
    for gy in range(step, CH, step):
        for gx in range(step, CW, step):
            a = 4 + (3 if (gx // step + gy // step) % 5 == 0 else 0)
            d.ellipse(
                (gx - 0.6 * S, gy - 0.6 * S, gx + 0.6 * S, gy + 0.6 * S),
                fill=(118, 150, 220, a),
            )

    # Sparse stars
    rng = random.Random(31)
    for _ in range(130):
        sx = rng.uniform(0, W) * S
        sy = rng.uniform(0, H) * S
        sr = rng.uniform(0.4, 1.2) * S
        a = rng.randint(10, 44)
        col = rng.choice([(180, 220, 255), (140, 180, 255), (220, 200, 255)])
        d.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=rgba(col, a))

    # Top accent line
    bar = h_gradient(
        (CW, 4 * S), [(34, 211, 238), (96, 165, 250), (129, 140, 248), (192, 132, 252)]
    )
    canvas.alpha_composite(bar.convert("RGBA"), (0, 0))
    glow = Image.new("RGBA", (CW, 12 * S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rectangle((0, 0, CW, 3 * S), fill=(96, 165, 250, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(5 * S))
    canvas.alpha_composite(glow, (0, 0))

    return canvas


# ---------------------------------------------------------------------------
# Small drawing primitives
# ---------------------------------------------------------------------------
def pill(draw, box, radius, fill, outline, width=1):
    rounded_rect(draw, box, radius, fill=fill, outline=outline, width=width)


def check_badge(draw, cx, cy, r, color=(52, 211, 153)):
    draw.ellipse(
        ((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S),
        fill=rgba(color, 34),
        outline=rgba(color, 160),
        width=max(1, int(0.8 * S)),
    )
    draw.line(
        [((cx - r * 0.42) * S, cy * S), ((cx - r * 0.08) * S, (cy + r * 0.34) * S)],
        fill=rgba(color, 255),
        width=max(1, int(1.3 * S)),
    )
    draw.line(
        [
            ((cx - r * 0.08) * S, (cy + r * 0.34) * S),
            ((cx + r * 0.5) * S, (cy - r * 0.38) * S),
        ],
        fill=rgba(color, 255),
        width=max(1, int(1.3 * S)),
    )


def check_mark(draw, x, y, size, color=(52, 211, 153), width=1.4):
    draw.line(
        [
            ((x - size * 0.45) * S, y * S),
            ((x - size * 0.05) * S, (y + size * 0.38) * S),
        ],
        fill=rgba(color, 255),
        width=max(1, int(width * S)),
    )
    draw.line(
        [
            ((x - size * 0.05) * S, (y + size * 0.38) * S),
            ((x + size * 0.55) * S, (y - size * 0.42) * S),
        ],
        fill=rgba(color, 255),
        width=max(1, int(width * S)),
    )


def som_badge(draw, x, y, label, color, size=20):
    rounded_rect(
        draw,
        (x, y, x + size, y + size),
        6,
        fill=(4, 10, 24, 235),
        outline=rgba(color, 220),
        width=1,
    )
    text(
        draw,
        (x + size / 2, y + size / 2 + 0.5),
        label,
        font(F_MONO_BOLD, 9),
        rgba(color, 255),
        anchor="mm",
    )


def draw_product_icon(draw, x, y, kind, color):
    rounded_rect(
        draw,
        (x, y, x + 36, y + 36),
        9,
        fill=rgba(color, 26),
        outline=rgba(color, 90),
        width=1,
    )
    if kind == "keyboard":
        for row in range(2):
            for col in range(3):
                kx = x + 8 + col * 8
                ky = y + 11 + row * 9
                rounded_rect(
                    draw, (kx, ky, kx + 5.5, ky + 6), 1.5, fill=rgba(color, 160)
                )
    else:
        rounded_rect(
            draw,
            (x + 11, y + 8, x + 25, y + 28),
            7,
            fill=rgba(color, 130),
            outline=rgba(color, 210),
            width=1,
        )
        draw.line(
            [((x + 18) * S, (y + 11) * S), ((x + 18) * S, (y + 16) * S)],
            fill=rgba((6, 12, 28), 255),
            width=max(1, int(1 * S)),
        )


# ---------------------------------------------------------------------------
# Left content
# ---------------------------------------------------------------------------
def draw_left(canvas: Image.Image):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    # Top pill
    pill_txt = "REAL HTTP SHOP   ·   REAL EDGE   ·   CONSTRAINT PLANNING"
    f_pill = font(F_SEMI, 14)
    pw, _ = measure(f_pill, pill_txt)
    pill(
        d, (96, 88, 96 + pw + 44, 126), 19, (255, 255, 255, 14), (120, 160, 235, 78), 1
    )
    d.ellipse((112 * S, 101 * S, 120 * S, 109 * S), fill=(74, 222, 128, 255))
    text(d, (129, 107), pill_txt, f_pill, (184, 202, 236, 255), anchor="lm")

    # Vertical accent rail
    accent = (
        h_gradient(
            (188 * S, 3 * S),
            [(34, 211, 238), (129, 140, 248), (192, 132, 252)],
        )
        .rotate(90, expand=True)
        .convert("RGBA")
    )
    accent.putalpha(215)
    accent_glow = accent.filter(ImageFilter.GaussianBlur(4 * S))
    layer.alpha_composite(accent_glow, (70 * S, 150 * S))
    layer.alpha_composite(accent, (72 * S, 150 * S))

    # Title
    f_title = font(F_BOLD, 190)
    gradient_text(
        canvas,
        (92, 150),
        "Step-RL",
        f_title,
        [(245, 250, 255), (125, 211, 252), (129, 140, 248), (232, 121, 249)],
        glow=(96, 165, 250),
        glow_alpha=90,
        glow_blur=18,
    )

    # Version badge
    title_w = measure(f_title, "Step-RL")[0]
    bx = 92 + title_w + 24
    by = 238
    pill(
        d, (bx, by, bx + 132, by + 56), 17, (79, 70, 229, 58), (165, 180, 252, 150), 1.2
    )
    text(
        d,
        (bx + 66, by + 28),
        "v3.5",
        font(F_BOLD, 26),
        (232, 238, 255, 255),
        anchor="mm",
    )

    # English subtitle
    text(
        d,
        (96, 386),
        "Constraint-Aware Cross-Layout RL",
        font(F_SEMI, 39),
        (232, 240, 255, 255),
        shadow=(0, 0, 0, 130),
        shadow_off=(0, 2),
    )

    # Chinese tagline
    text(
        d,
        (96, 438),
        "理解约束 · 编译任务 · 跨布局执行 · 结果可验证",
        font(F_CN, 26),
        (170, 190, 224, 255),
    )

    # Divider
    line = Image.new("RGBA", (CW, 2 * S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    for i in range(880 * S):
        a = int(150 * (1 - i / (880 * S)))
        ld.line([(i, 0), (i, 2 * S)], fill=(120, 150, 210, a))
    canvas.alpha_composite(line, (96 * S, 492 * S))

    # Feature chips
    chips = [
        ("Qwen3-0.6B", (34, 211, 238)),
        ("LoRA", (96, 165, 250)),
        ("Playwright", (129, 140, 248)),
        ("Step-GRPO", (192, 132, 252)),
        ("16GB 单卡", (244, 114, 182)),
    ]
    f_chip = font(F_CN, 17)
    cx = 96
    for label, col in chips:
        tw, _ = measure(f_chip, label)
        w = tw + 34
        pill(d, (cx, 516, cx + w, 558), 21, rgba(col, 22), rgba(col, 110), 1)
        d.ellipse(((cx + 14) * S, 534 * S, (cx + 20) * S, 540 * S), fill=rgba(col, 255))
        text(d, (cx + 27, 537), label, f_chip, (222, 233, 250, 255), anchor="lm")
        cx += w + 11

    # Result bars
    bars = [
        (
            "约束任务规划",
            "预算 / 最值 / 数量 / 缺货替代 → 可验证 TaskSpec",
            (34, 211, 238),
        ),
        (
            "跨布局语义迁移",
            "未见布局 + 重渲染 + ID churn 仍 100%",
            (167, 139, 250),
        ),
        ("语义 SoM 动作", "DOM id 全扰动后 0 非法动作", (74, 222, 128)),
    ]
    f_bar_title = font(F_CN_BOLD, 19)
    f_bar_body = font(F_CN, 17)
    by = 586
    for title, body, col in bars:
        pill(d, (96, by, 980, by + 56), 14, rgba(col, 20), rgba(col, 100), 1)
        d.rectangle((98 * S, (by + 5) * S, 101 * S, (by + 51) * S), fill=rgba(col, 230))
        d.ellipse(
            ((116) * S, (by + 22) * S, (124) * S, (by + 30) * S), fill=rgba(col, 255)
        )
        text(d, (134, by + 28), title, f_bar_title, (232, 240, 255, 255), anchor="lm")
        tw, _ = measure(f_bar_title, title)
        text(
            d,
            (134 + tw + 18, by + 28),
            body,
            f_bar_body,
            (166, 185, 220, 255),
            anchor="lm",
        )
        by += 64

    # Metrics
    metrics = [
        ("100%", "8 条约束指令成功率", (125, 211, 252)),
        ("12.5%", "关键词基线", (244, 114, 182)),
        ("100%", "跨布局 + ID churn", (74, 222, 128)),
        ("47", "真实测试", (167, 139, 250)),
    ]
    f_val = font(F_SEMI, 38)
    f_lab = font(F_CN, 16)
    mx = 96
    my = 790
    col_w = 224
    for i, (value, label, col) in enumerate(metrics):
        if i > 0:
            d.line(
                [(mx - 18) * S, my * S, (mx - 18) * S, (my + 68) * S],
                fill=(255, 255, 255, 32),
                width=max(1, int(1 * S)),
            )
        text(d, (mx, my), value, f_val, rgba(col, 255), anchor="la")
        text(d, (mx + 1, my + 47), label, f_lab, (150, 170, 206, 255), anchor="la")
        mx += col_w

    # Footer
    text(
        d,
        (96, 910),
        "ShaneLiu04  ·  github.com/ShaneLiu04/Step-RL",
        font(F_LIGHT, 16),
        (128, 146, 186, 255),
        anchor="lm",
    )
    text(
        d,
        (1824, 910),
        "REAL EPISODES · FIXED SEED",
        font(F_MONO, 10),
        (104, 122, 162, 255),
        anchor="rm",
    )

    canvas.alpha_composite(layer)


# ---------------------------------------------------------------------------
# Right panel: browser + verifier + hierarchy
# ---------------------------------------------------------------------------
def draw_browser_card(canvas: Image.Image):
    BX0, BY0, BX1, BY1 = 1072, 146, 1800, 430
    panel(
        canvas,
        (BX0, BY0, BX1, BY1),
        18,
        (8, 16, 34, 222),
        [(34, 211, 238), (96, 165, 250), (129, 140, 248)],
        border_alpha=95,
        border_w=1.2,
    )
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    # Browser chrome
    for i, col in enumerate([(248, 113, 113), (251, 191, 36), (52, 211, 153)]):
        cx = 1092 + i * 14
        d.ellipse(
            ((cx - 3.6) * S, 163.4 * S, (cx + 3.6) * S, 170.6 * S), fill=rgba(col, 235)
        )
    pill(d, (1138, 155, 1462, 179), 12, (255, 255, 255, 12), (255, 255, 255, 30), 1)
    d.ellipse((1148 * S, 163 * S, 1154 * S, 169 * S), fill=(52, 211, 153, 235))
    text(
        d,
        (1161, 167),
        "shop.local/cart",
        font(F_MONO, 10),
        (186, 204, 234, 255),
        anchor="lm",
    )
    pill(d, (1680, 155, 1782, 179), 12, (34, 197, 94, 30), (74, 222, 128, 115), 1)
    text(
        d,
        (1731, 167),
        "SoM ON",
        font(F_MONO_BOLD, 9),
        (134, 239, 172, 255),
        anchor="mm",
    )

    # Page header
    text(
        d, (1094, 198), "StepShop", font(F_SEMI, 18), (240, 245, 255, 255), anchor="la"
    )
    text(
        d,
        (1094, 218),
        "真实 HTTP 商城",
        font(F_CN, 9),
        (162, 182, 218, 255),
        anchor="la",
    )
    text(
        d,
        (1780, 206),
        "商品    购物车",
        font(F_CN, 9),
        (162, 182, 218, 255),
        anchor="rm",
    )

    # Constraint instruction banner
    pill(d, (1094, 226, 1780, 260), 10, (251, 191, 36, 18), (251, 191, 36, 95), 1)
    d.ellipse((1108 * S, 239 * S, 1116 * S, 247 * S), fill=(251, 191, 36, 245))
    text(
        d,
        (1124, 243),
        "约束：预算 ≤ ¥500 · 2 件 · 缺货可替代",
        font(F_CN, 10.5),
        (245, 225, 178, 255),
        anchor="lm",
    )
    text(
        d,
        (1766, 243),
        "PARSED ✓",
        font(F_MONO_BOLD, 8),
        (134, 239, 172, 255),
        anchor="rm",
    )

    # Product cards
    # P3 is out of stock; P4 is the recommended substitute.
    pill(d, (1094, 268, 1306, 380), 12, (255, 255, 255, 8), (251, 191, 36, 65), 1)
    draw_product_icon(d, 1106, 278, "keyboard", (251, 191, 36))
    text(
        d,
        (1152, 280),
        "机械键盘 P3",
        font(F_CN_BOLD, 12.5),
        (236, 243, 255, 255),
        anchor="la",
    )
    text(
        d,
        (1152, 302),
        "¥299",
        font(F_MONO_BOLD, 11.5),
        (251, 191, 36, 255),
        anchor="la",
    )
    text(
        d,
        (1152, 322),
        "缺货 · 替代可用",
        font(F_CN, 8.5),
        (245, 190, 130, 255),
        anchor="la",
    )
    pill(d, (1106, 344, 1294, 370), 9, (251, 191, 36, 24), (251, 191, 36, 100), 1)
    text(
        d,
        (1198, 357),
        "查看替代",
        font(F_CN, 11.5),
        (245, 225, 190, 255),
        anchor="mm",
    )
    som_badge(d, 1270, 348, "e1", (251, 191, 36), 20)

    pill(d, (1318, 268, 1530, 380), 12, (255, 255, 255, 10), (96, 165, 250, 110), 1)
    draw_product_icon(d, 1330, 278, "mouse", (96, 165, 250))
    text(
        d,
        (1376, 280),
        "无线鼠标 P4",
        font(F_CN_BOLD, 12.5),
        (236, 243, 255, 255),
        anchor="la",
    )
    text(
        d,
        (1376, 302),
        "¥159",
        font(F_MONO_BOLD, 11.5),
        (96, 165, 250, 255),
        anchor="la",
    )
    text(
        d,
        (1376, 322),
        "库存 3 · 推荐替代",
        font(F_CN, 8.5),
        (150, 230, 190, 255),
        anchor="la",
    )
    pill(d, (1330, 344, 1518, 370), 9, (96, 165, 250, 30), (96, 165, 250, 125), 1)
    text(
        d,
        (1422, 357),
        "加入购物车",
        font(F_CN, 11.5),
        (232, 241, 255, 255),
        anchor="mm",
    )
    som_badge(d, 1494, 348, "e2", (96, 165, 250), 20)

    # Cart panel
    pill(d, (1544, 268, 1780, 380), 12, (255, 255, 255, 10), (74, 222, 128, 90), 1)
    text(
        d,
        (1560, 280),
        "购物车",
        font(F_CN_BOLD, 11.5),
        (236, 243, 255, 255),
        anchor="la",
    )
    text(d, (1764, 280), "2", font(F_MONO_BOLD, 9), (134, 239, 172, 255), anchor="ra")
    d.line(
        [(1560 * S, 294 * S), (1764 * S, 294 * S)],
        fill=(255, 255, 255, 22),
        width=max(1, int(1 * S)),
    )
    text(d, (1560, 302), "P4 × 2", font(F_MONO, 9.5), (214, 226, 246, 255), anchor="la")
    text(d, (1764, 302), "¥318", font(F_MONO, 9.5), (214, 226, 246, 255), anchor="ra")
    text(
        d,
        (1560, 318),
        "替代 P3 · 预算内",
        font(F_CN, 8),
        (150, 230, 190, 255),
        anchor="la",
    )
    d.line(
        [(1560 * S, 330 * S), (1764 * S, 330 * S)],
        fill=(255, 255, 255, 22),
        width=max(1, int(1 * S)),
    )
    text(d, (1560, 338), "合计", font(F_CN, 8.5), (156, 176, 210, 255), anchor="la")
    text(
        d,
        (1764, 338),
        "¥318",
        font(F_MONO_BOLD, 11.5),
        (134, 239, 172, 255),
        anchor="ra",
    )
    pill(d, (1556, 350, 1768, 376), 9, (34, 197, 94, 30), (74, 222, 128, 125), 1)
    text(d, (1648, 363), "结算", font(F_CN_BOLD, 11), (224, 252, 234, 255), anchor="mm")
    som_badge(d, 1740, 354, "e3", (74, 222, 128), 20)

    # Click ripple on e2
    cx, cy = 1494 + 10, 348 + 10
    for r, a in ((28, 28), (20, 48), (13, 85)):
        d.ellipse(
            ((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S),
            outline=(96, 165, 250, a),
            width=max(1, int(1 * S)),
        )
    d.polygon(
        [
            ((cx + 12) * S, (cy - 22) * S),
            ((cx + 12) * S, (cy - 4) * S),
            ((cx + 16) * S, (cy - 8) * S),
            ((cx + 20) * S, (cy - 1) * S),
            ((cx + 23) * S, (cy - 3) * S),
            ((cx + 19) * S, (cy - 10) * S),
            ((cx + 25) * S, (cy - 10) * S),
        ],
        fill=(244, 249, 255, 240),
    )

    # Planner output chip
    pill(d, (1094, 390, 1442, 416), 10, (0, 0, 0, 130), (34, 211, 238, 85), 1)
    text(
        d,
        (1108, 403),
        '{"plan":["P4x2","checkout"],"alt":"P3>P4"}',
        font(F_MONO, 10),
        (185, 247, 255, 255),
        anchor="lm",
    )
    check_badge(d, 1424, 403, 7, (52, 211, 153))
    d.ellipse((1456 * S, 399 * S, 1464 * S, 407 * S), fill=(74, 222, 128, 230))
    text(
        d,
        (1470, 403),
        "P3 缺货 → P4 替代",
        font(F_CN, 9),
        (150, 230, 190, 255),
        anchor="lm",
    )

    canvas.alpha_composite(layer)


def draw_verifier_card(canvas: Image.Image):
    VX0, VY0, VX1, VY1 = 1072, 446, 1422, 812
    panel(
        canvas,
        (VX0, VY0, VX1, VY1),
        18,
        (8, 16, 34, 222),
        [(167, 139, 250), (129, 140, 248)],
        border_alpha=92,
        border_w=1.2,
    )
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    text(
        d,
        (1094, 468),
        "Verifier Φ(s)",
        font(F_SEMI, 20),
        (240, 245, 255, 255),
        anchor="la",
    )
    text(
        d,
        (1094, 494),
        "server-side predicates",
        font(F_MONO, 9.5),
        (162, 182, 218, 255),
        anchor="la",
    )

    text(d, (1094, 522), "Φ", font(F_SEMI, 30), (180, 156, 255, 255), anchor="la")
    text(d, (1128, 510), "1.00", font(F_BOLD, 54), (52, 211, 153, 255), anchor="la")
    text(
        d,
        (1096, 578),
        "8 / 8 predicates satisfied",
        font(F_MONO, 9.5),
        (134, 239, 172, 255),
        anchor="la",
    )

    gx, gy, gr = 1370, 548, 26
    d.arc(
        ((gx - gr) * S, (gy - gr) * S, (gx + gr) * S, (gy + gr) * S),
        -90,
        270,
        fill=(52, 211, 153, 255),
        width=max(1, int(2.5 * S)),
    )
    check_badge(d, gx, gy, 9, (52, 211, 153))

    predicates = [
        "search_done",
        "product_viewed",
        "cart_contains",
        "cart_viewed",
        "checkout_viewed",
        "name_filled",
        "address_filled",
        "order_placed",
    ]
    px0, py0 = 1102, 610
    col_w, row_h = 152, 30
    for i, name in enumerate(predicates):
        col = i // 4
        row = i % 4
        x = px0 + col * col_w
        y = py0 + row * row_h
        check_badge(d, x, y, 6, (52, 211, 153))
        text(
            d,
            (x + 14, y),
            name,
            font(F_MONO, 10.5),
            (210, 222, 246, 255),
            anchor="lm",
        )
        check_mark(d, x + 140, y, 8, (52, 211, 153), 1.2)

    pill(d, (1094, 772, 1400, 780), 4, (255, 255, 255, 20), None, 0)
    bar = h_gradient((306 * S, 8 * S), [(52, 211, 153), (34, 211, 238)]).convert("RGBA")
    bar.putalpha(225)
    canvas.alpha_composite(bar, (1094 * S, 772 * S))
    text(
        d,
        (1094, 792),
        "finish does not grant success",
        font(F_MONO, 8.5),
        (150, 170, 206, 255),
        anchor="la",
    )

    canvas.alpha_composite(layer)


def draw_hierarchy_card(canvas: Image.Image):
    HX0, HY0, HX1, HY1 = 1438, 446, 1800, 812
    panel(
        canvas,
        (HX0, HY0, HX1, HY1),
        18,
        (8, 16, 34, 222),
        [(244, 114, 182), (129, 140, 248)],
        border_alpha=92,
        border_w=1.2,
    )
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    text(
        d,
        (1460, 468),
        "Constraint Planner",
        font(F_SEMI, 20),
        (240, 245, 255, 255),
        anchor="la",
    )
    text(
        d,
        (1460, 494),
        "instruction → TaskSpec → adapters",
        font(F_MONO, 8.5),
        (162, 182, 218, 255),
        anchor="la",
    )

    rows = [
        ("Planner", "约束 → 可验证 TaskSpec", (251, 191, 36)),
        ("SFT", "L1–L2 基础流程", (34, 211, 238)),
        ("VGDP", "L3 数量控制", (167, 139, 250)),
        ("Sparse", "L4–L5 结算流程", (74, 222, 128)),
    ]
    ry = 512
    for name, role, col in rows:
        pill(d, (1460, ry, 1778, ry + 54), 12, rgba(col, 18), rgba(col, 90), 1)
        d.rectangle(
            (1462 * S, (ry + 6) * S, 1465 * S, (ry + 48) * S), fill=rgba(col, 230)
        )
        text(
            d,
            (1478, ry + 14),
            name,
            font(F_SEMI, 15.5),
            (236, 243, 255, 255),
            anchor="la",
        )
        text(
            d,
            (1478, ry + 35),
            role,
            font(F_CN, 9.5),
            (178, 196, 228, 255),
            anchor="la",
        )
        check_badge(d, 1758, ry + 27, 8, col)
        ry += 64

    pill(d, (1460, 770, 1778, 802), 12, (34, 197, 94, 28), (74, 222, 128, 105), 1)
    text(
        d,
        (1468, 786),
        "8/8 constraints · cross-layout 100% · 0 illegal",
        font(F_MONO, 8.5),
        (134, 239, 172, 255),
        anchor="lm",
    )

    canvas.alpha_composite(layer)


def draw_right(canvas: Image.Image):
    RX0, RY0, RX1, RY1 = 1040, 86, 1832, 870
    panel(
        canvas,
        (RX0, RY0, RX1, RY1),
        30,
        (255, 255, 255, 12),
        [(34, 211, 238), (129, 140, 248), (192, 132, 252)],
        border_alpha=80,
        border_w=1.4,
    )
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    text(
        d,
        (1072, 120),
        "CONSTRAINT PARSER   ·   SEMANTIC BROWSER   ·   VERIFIER Φ",
        font(F_MONO_BOLD, 10),
        (160, 182, 222, 245),
        anchor="lm",
    )
    d.ellipse((1698 * S, 115 * S, 1706 * S, 123 * S), fill=(74, 222, 128, 220))
    text(
        d,
        (1714, 120),
        "AR006 · REAL EPISODE",
        font(F_MONO_BOLD, 9),
        (134, 239, 172, 235),
        anchor="lm",
    )
    text(
        d,
        (1072, 836),
        "真实 HTTP 商城 · 真实 Edge · 真实 episode JSON · 固定 seed",
        font(F_CN, 9.5),
        (148, 168, 204, 255),
        anchor="la",
    )
    canvas.alpha_composite(layer)


def main():
    canvas = build_background()

    draw_right(canvas)
    draw_browser_card(canvas)
    draw_verifier_card(canvas)
    draw_hierarchy_card(canvas)
    draw_left(canvas)

    full = canvas.convert("RGB")
    full_dir = ROOT / "outputs" / "ar001"
    full_dir.mkdir(parents=True, exist_ok=True)
    full.resize((W, H), Image.LANCZOS).save(
        full_dir / "cover_full.png", "PNG", optimize=True
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = full.resize((1600, 800), Image.LANCZOS)
    out.save(OUT, "JPEG", quality=84, optimize=True, subsampling=0)
    print(
        f"[OK] {OUT}  ({out.size[0]}x{out.size[1]}, {OUT.stat().st_size / 1024:.1f} KB)"
    )


if __name__ == "__main__":
    main()
