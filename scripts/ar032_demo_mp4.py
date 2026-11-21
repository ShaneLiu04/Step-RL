"""Build AR032 MP4 from real screenshots/GIF frames (no mock)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "ar032_demo.mp4"
FONT = Path("C:/Windows/Fonts/msyh.ttc")
W, H = 560, 352
CAP_H = 36


def caption(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGB", (W, H + CAP_H), (8, 12, 26))
    ratio = min(W / image.width, H / image.height)
    resized = image.resize(
        (int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS
    )
    canvas.paste(resized, ((W - resized.width) // 2, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(str(FONT), 17)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, H + 8), text, fill=(230, 238, 255), font=font)
    return canvas


def frames():
    result = []
    gif = ROOT / "docs" / "images" / "ar028_demo.gif"
    if gif.exists():
        image = Image.open(gif)
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            result.append(
                caption(
                    image.convert("RGB"),
                    "Local real Edge: cart -> checkout -> order (AR028)",
                )
            )
    evidence = [
        (
            "JD search (real): page opened, item_links=0",
            "outputs/ar032/jd/20261121_184434_bb57d6/search.png",
        ),
        (
            "Taobao search (real): empty title / anti-bot",
            "outputs/ar032/taobao/20261121_184451_202212/search.png",
        ),
        (
            "Amazon search (real): read-only page loaded",
            "outputs/ar032/amazon/20261121_184503_f11087/search.png",
        ),
    ]
    for text, relative in evidence:
        path = ROOT / relative
        if path.exists():
            result.append(caption(Image.open(path).convert("RGB"), text))
    return result or [caption(Image.new("RGB", (W, H), (10, 15, 30)), "No real frames")]


def main():
    images = frames()
    ffmpeg = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H + CAP_H}",
        "-r",
        "3",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "32",
        "-movflags",
        "+faststart",
        str(OUT),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for image in images:
        process.stdin.write(image.tobytes())
    process.stdin.close()
    process.wait()
    print({"mp4": str(OUT), "bytes": OUT.stat().st_size, "frames": len(images)})


if __name__ == "__main__":
    main()
