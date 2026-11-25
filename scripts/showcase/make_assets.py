"""Build README showcase assets from real captures.

    node scripts/showcase/record.mjs                      # live Studio sessions -> outputs/showcase/frames
    python scripts/showcase/make_assets.py [--skip-cli]   # -> docs/assets

* Studio scenes : CDP-recorded frames of real Edge runs -> GIF + JPG stills + hero composite
* Terminal      : real ``step-rl doctor / run / eval`` and quality-gate output rendered as GIF / JPG
* Brand         : banner / architecture / logo rendered from HTML (see banner.html, architecture.html)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOWCASE = ROOT / "outputs" / "showcase"

_FONTS = {
    "mono": ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/SFNSMono.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
    "cjk": ["C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    "sans": ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/SFNS.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "symbol": ["C:/Windows/Fonts/seguisym.ttf", "/System/Library/Fonts/Apple Symbols.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}
SYMBOLS = set("✓✗✔✘•")


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in _FONTS[kind]:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


# ── terminal renderer ───────────────────────────────────────────────────────

BG, BAR, FG, DIM = (14, 17, 23), (28, 32, 40), (214, 219, 228), (118, 126, 140)
GREEN, RED, AMBER, BLUE, CYAN, VIOLET = (72, 222, 160), (255, 99, 92), (255, 184, 76), (110, 168, 255), (94, 214, 236), (176, 148, 255)

RULES: List[Tuple[re.Pattern, Tuple[int, int, int]]] = [
    (re.compile(r"✓|\bPASS\b|\bREADY\b|\bCLEAN\b|\bSUCCESS\b|All checks passed!|\d+ passed"), GREEN),
    (re.compile(r"✗|\bFAIL(?:ED)?\b|NOT READY"), RED),
    (re.compile(r"(?<![\w-])!(?=\s)|\bwarn\b|\d+ skipped"), AMBER),
    (re.compile(r"→.*$"), DIM),
    (re.compile(r"\b0 LLM\b|\b0 tokens\b|\b0 LLM steps\b"), CYAN),
    (re.compile(r"\bAR0\d\d\b|\[[\w./-]+\]"), VIOLET),
]


def _spans(line: str):
    if line.startswith("$ "):
        return [("~/Step-RL ", BLUE), ("$ ", GREEN), (line[2:], (255, 255, 255))]
    if line.startswith("# "):
        return [(line, VIOLET)]
    colors = [FG] * len(line)
    for rx, col in RULES:
        for m in rx.finditer(line):
            for i in range(m.start(), m.end()):
                colors[i] = col
    spans: list = []
    for ch, col in zip(line, colors):
        if spans and spans[-1][1] == col:
            spans[-1] = (spans[-1][0] + ch, col)
        else:
            spans.append((ch, col))
    return spans


class Terminal:
    def __init__(self, width: int = 1280, rows: int = 26, size: int = 17, title: str = "step-rl — zsh") -> None:
        self.width, self.rows, self.title = width, rows, title
        self.f, self.fc, self.fs = font("mono", size), font("cjk", size - 1), font("symbol", size)
        self.line_h = int(size * 1.55)
        self.baseline = int(size * 1.1)
        self.pad, self.bar_h = 26, 40
        self.height = self.bar_h + self.pad * 2 + self.line_h * rows
        self.cols = int((width - self.pad * 2) / self.f.getlength("M"))

    def _font(self, ch: str) -> ImageFont.FreeTypeFont:
        if ch in SYMBOLS:
            return self.fs
        return self.f if ord(ch) < 0x2E80 else self.fc

    def _w(self, ch: str) -> float:
        return self._font(ch).getlength(ch)

    def wrap(self, text: str) -> List[str]:
        out: List[str] = []
        limit = self.width - self.pad * 2
        for raw in text.splitlines() or [""]:
            line, width = "", 0.0
            for ch in raw.rstrip():
                w = self._w(ch)
                if width + w > limit:
                    out.append(line)
                    line, width = "    ", self._w(" ") * 4
                line += ch
                width += w
            out.append(line)
        return out

    def render(self, lines: List[str], cursor: bool = False) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, self.width, self.bar_h], fill=BAR)
        for i, col in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
            d.ellipse([18 + i * 22, 14, 30 + i * 22, 26], fill=col)
        tf = font("sans", 14)
        d.text(((self.width - d.textlength(self.title, font=tf)) / 2, 11), self.title, font=tf, fill=DIM)
        visible = lines[-self.rows:]
        y, last_x = self.bar_h + self.pad, self.pad
        for ln in visible:
            x = self.pad
            for text, col in _spans(ln):
                for ch in text:
                    f = self._font(ch)
                    d.text((x, y + self.baseline), ch, font=f, fill=col, anchor="ls")
                    x += f.getlength(ch)
            last_x = x
            y += self.line_h
        if cursor and visible:
            cy = self.bar_h + self.pad + (len(visible) - 1) * self.line_h
            d.rectangle([last_x + 2, cy + 3, last_x + 11, cy + self.line_h - 5], fill=GREEN)
        return img


def window(img: Image.Image, radius: int = 16, margin: int = 36, bg=(236, 239, 245)) -> Image.Image:
    w, h = img.size
    canvas = Image.new("RGB", (w + margin * 2, h + margin * 2), bg)
    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle([margin, margin + 10, margin + w, margin + h + 10], radius, fill=110)
    canvas.paste(Image.new("RGB", canvas.size, (40, 44, 60)), mask=shadow.filter(ImageFilter.GaussianBlur(18)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=255)
    canvas.paste(img, (margin, margin), mask)
    return canvas


def save_gif(frames: List[Image.Image], durations: List[int], path: Path, colors: int = 160) -> None:
    kept_f: List[Image.Image] = []
    kept_d: List[int] = []
    for fr, du in zip(frames, durations):
        if kept_f and ImageChops.difference(kept_f[-1], fr).getbbox() is None:
            kept_d[-1] += du
            continue
        kept_f.append(fr)
        kept_d.append(du)
    pal = [f.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in kept_f]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=kept_d, loop=0, optimize=True, disposal=1)
    print(f"  gif {path.name}: {len(pal)} frames, {path.stat().st_size / 1e6:.2f} MB")


def save_jpg(img: Image.Image, path: Path, quality: int = 90) -> None:
    img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    print(f"  jpg {path.name}: {img.size[0]}x{img.size[1]}, {path.stat().st_size / 1e3:.0f} KB")


# ── real command capture ────────────────────────────────────────────────────

def capture(args: List[str], env: dict | None = None) -> str:
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})})
    text = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout + proc.stderr).rstrip()
    root = str(ROOT)
    for variant in {root, root.replace("\\", "/"), root.replace("\\", "\\\\")}:
        text = text.replace(variant, "~/Step-RL")
    return text.replace("\\", "/") if "~/Step-RL" in text else text


def build_cli(out: Path) -> None:
    py = sys.executable
    story = [
        ("step-rl doctor --live", [py, "-m", "step_rl", "doctor", "--live"]),
        ("step-rl run --scenario cart-to-order", [py, "-m", "step_rl", "run", "--scenario", "cart-to-order"]),
        ("step-rl eval --suite smoke --concurrency 3", [py, "-m", "step_rl", "eval", "--suite", "smoke", "--concurrency", "3"]),
    ]
    term = Terminal(width=1280, rows=30, title="step-rl — deploy · verify · evaluate")
    transcript: List[Tuple[str, str]] = []
    for cmd, args in story:
        print(f"[cli] $ {cmd}")
        t0 = time.perf_counter()
        text = capture(args)
        print(f"      {time.perf_counter() - t0:.1f}s, {len(text.splitlines())} lines")
        transcript.append((cmd, text))
    (SHOWCASE / "cli-transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1), "utf-8")

    frames: List[Image.Image] = []
    durs: List[int] = []
    buf: List[str] = []
    for cmd, text in transcript:
        for i in range(0, len(cmd) + 1, 4):
            frames.append(term.render(buf + ["$ " + cmd[:i]], cursor=True))
            durs.append(45)
        buf.append("$ " + cmd)
        frames.append(term.render(buf))
        durs.append(400)
        body = term.wrap(text)
        for i in range(0, len(body), 2):
            buf.extend(body[i:i + 2])
            frames.append(term.render(buf))
            durs.append(90)
        durs[-1] = 2200
        buf.append("")
    durs[-1] = 4000
    save_gif([window(f) for f in frames], durs, out / "cli-step-rl.gif", colors=96)

    lines: List[str] = []
    for cmd, text in transcript:
        lines += ["$ " + cmd, *term.wrap(text), ""]
    tall = Terminal(width=1280, rows=len(lines), title="step-rl — real session transcript")
    save_jpg(window(tall.render(lines)), out / "cli-step-rl.jpg")


def build_quality(out: Path) -> None:
    py = sys.executable
    print("[quality] ruff · pytest · privacy-scan …")
    ruff = capture([py, "-m", "ruff", "check", "step_rl", "tests", "scripts"])
    tests = [ln for ln in capture([py, "-m", "pytest", "tests", "-q"]).splitlines()
             if re.search(r"\d+ (passed|failed)", ln)]
    privacy = capture([py, "-m", "step_rl", "privacy-scan"])
    lines = ["$ ruff check step_rl tests scripts", ruff, "", "$ pytest tests -q", *tests[-1:], "",
             "$ step-rl privacy-scan", privacy]
    term = Terminal(width=1280, rows=1, title="quality gates — Step-RL")
    wrapped: List[str] = []
    for ln in lines:
        wrapped += term.wrap(ln) if ln else [""]
    term = Terminal(width=1280, rows=len(wrapped), title="quality gates — Step-RL")
    save_jpg(window(term.render(wrapped)), out / "quality-gates.jpg")


# ── Studio scenes ───────────────────────────────────────────────────────────

SCENES = {"order": "studio-order.gif", "budget": "studio-budget.gif", "layout": "studio-layout-v3.gif",
          "tour": "studio-tour.gif"}
STILLS = {
    "01-home": "studio-home.jpg",
    "02-composer": "studio-composer.jpg",
    "03-approval": "studio-approval.jpg",
    "04-order-done": "studio-order-done.jpg",
    "05-budget-done": "studio-budget-done.jpg",
    "06-dark-layout-v3": "studio-dark-layout-v3.jpg",
    "07-skills": "studio-skills.jpg",
    "07-evidence": "studio-evidence.jpg",
    "07-evidence-ledger": "studio-evidence-ledger.jpg",
    "07-audit": "studio-audit.jpg",
    "08-system": "studio-system.jpg",
    "09-dark-evidence": "studio-dark-evidence.jpg",
    "10-dark-skills": "studio-dark-skills.jpg",
}


def build_studio(frames_dir: Path, out: Path) -> None:
    print(f"[studio] assembling from {frames_dir} …")
    for scene, name in SCENES.items():
        meta_path = frames_dir / scene / "frames.json"
        if not meta_path.is_file():
            print(f"  skip {scene}: no frames")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        imgs = [Image.open(m["file"]).convert("RGB").resize((1200, 750), Image.LANCZOS) for m in meta]
        durs = []
        for i, m in enumerate(meta):
            gap = (meta[i + 1]["t"] - m["t"]) if i + 1 < len(meta) else 0
            durs.append(int(max(80, min(gap, 1200)) + m.get("hold", 0)))
        durs[-1] = max(durs[-1], 2800)
        save_gif(imgs, durs, out / name, colors=176)
    stills = frames_dir / "stills"
    for src, dst in STILLS.items():
        p = stills / f"{src}.png"
        if p.is_file():
            save_jpg(Image.open(p), out / dst, quality=88)
    light, dark = stills / "04-order-done.png", stills / "06-dark-layout-v3.png"
    if light.is_file() and dark.is_file():
        build_hero(Image.open(light).convert("RGB"), Image.open(dark).convert("RGB"), out / "hero.jpg")


def build_hero(back: Image.Image, front: Image.Image, path: Path) -> None:
    W, H = 2400, 1260
    canvas = Image.new("RGB", (W, H))
    top, bottom = (11, 19, 34), (7, 11, 20)
    d = ImageDraw.Draw(canvas)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    for box, col in (([-300, -400, 1100, 700], (46, 242, 194)), ([1500, 650, 2800, 1700], (139, 124, 255))):
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse(box, fill=90)
        canvas.paste(Image.new("RGB", (W, H), col), mask=glow.filter(ImageFilter.GaussianBlur(170)))

    def place(img: Image.Image, x: int, y: int, w: int) -> None:
        h = int(img.size[1] * w / img.size[0])
        im = img.resize((w, h), Image.LANCZOS)
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).rounded_rectangle([x, y + 26, x + w, y + h + 26], 26, fill=150)
        canvas.paste(Image.new("RGB", (W, H), (0, 0, 0)), mask=shadow.filter(ImageFilter.GaussianBlur(36)))
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], 22, fill=255)
        canvas.paste(im, (x, y), mask)

    place(back, 90, 80, 1560)
    place(front, 880, 400, 1420)
    save_jpg(canvas, path, quality=88)


def build_brand(out: Path) -> None:
    shutil.copyfile(ROOT / "step_rl" / "console" / "static" / "logo.svg", out / "logo.svg")
    for name in ("banner", "architecture"):
        p = SHOWCASE / f"{name}.png"
        if p.is_file():
            save_jpg(Image.open(p), out / f"{name}.jpg", quality=92)
    logo = SHOWCASE / "logo.png"
    if logo.is_file():
        Image.open(logo).resize((256, 256), Image.LANCZOS).save(out / "logo-256.png", optimize=True)
        print("  png logo-256.png")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=Path, default=SHOWCASE / "frames")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "assets")
    ap.add_argument("--skip-cli", action="store_true")
    ap.add_argument("--skip-quality", action="store_true")
    ap.add_argument("--skip-studio", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    build_brand(args.out)
    if not args.skip_studio:
        build_studio(args.frames, args.out)
    if not args.skip_cli:
        build_cli(args.out)
    if not args.skip_quality:
        build_quality(args.out)


if __name__ == "__main__":
    main()
