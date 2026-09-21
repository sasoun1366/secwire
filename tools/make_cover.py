#!/usr/bin/env python3
"""Draw secwire/assets/cover.png — the picture used on days the story has none.

Many of the most useful stories (a CISA advisory, a vendor bulletin) come with no
photograph at all, and the channel's house style is a photograph with a caption.
This is the picture for those days: a quiet, branded card, drawn once here and
committed to the repository, so the daily job only ever has to upload a file it
already has. Pillow is needed to *draw* it; nothing at runtime needs Pillow.

    python3 tools/make_cover.py
"""

from __future__ import annotations

import pathlib
import random
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parents[1] / "secwire" / "assets" / "cover.png"
SIZE = (1200, 630)
FONT_DIR = pathlib.Path(__file__).resolve().parents[1] / "secwire" / "assets"
BG_TOP, BG_BOTTOM = (13, 27, 42), (8, 16, 26)
ACCENT = (90, 178, 255)
DIM = (110, 140, 170)


def font(name: str, size: int):
    """Vazirmatn (OFL, bundled): it draws Persian properly and has Latin glyphs too."""
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def gradient(size):
    width, height = size
    base = Image.new("RGB", size, BG_TOP)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        ratio = y / float(height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio) for i in range(3)),
        )
    return base


def veil(image, size, until: int = 820):
    """Darken the left side so the text sits on a calm field, not on the lines."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = size
    for x in range(width):
        if x >= until:
            break
        alpha = int(232 * (1 - (x / float(until)) ** 1.6))
        draw.line([(x, 0), (x, height)], fill=(6, 14, 24, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def constellation(draw, size, seed: int = 7):
    """A few nodes and lines: the network this channel is about, drawn quietly."""
    random.seed(seed)
    width, height = size
    points = [(random.randint(60, width - 60), random.randint(70, height - 90)) for _ in range(22)]
    for index, point in enumerate(points):
        for other in points[index + 1:]:
            distance = ((point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2) ** 0.5
            if distance < 210:
                shade = int(40 + 60 * (1 - distance / 210.0))
                draw.line([point, other], fill=(shade, shade + 12, shade + 30), width=1)
    for point in points:
        radius = random.choice((2, 2, 3, 4))
        draw.ellipse(
            [point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius],
            fill=(70, 120, 165),
        )


def main() -> int:
    width, height = SIZE
    image = gradient(SIZE)
    draw = ImageDraw.Draw(image)
    constellation(draw, SIZE)
    image = veil(image, SIZE)
    draw = ImageDraw.Draw(image)

    # A thin accent rule under the wordmark, the only saturated colour on the card.
    draw.rectangle([80, 232, 232, 238], fill=ACCENT)

    draw.text((80, 120), "secwire", font=font("Vazirmatn-Bold.ttf", 92), fill=(240, 246, 252))
    draw.text((80, 268), "Daily network security", font=font("Vazirmatn-Regular.ttf", 40), fill=DIM)
    draw.text((80, 330), "مهم‌ترین خبر روزِ امنیت شبکه — هر روز، ساعت ۱۰ صبح",
              font=font("Vazirmatn-Bold.ttf", 34), fill=(150, 175, 200),
              direction="rtl", language="fa")
    draw.text((80, height - 110), "@luyavaai", font=font("Vazirmatn-Bold.ttf", 44), fill=ACCENT)
    draw.text((80, height - 56), "github.com/sasoun1366/secwire",
              font=font("Vazirmatn-Regular.ttf", 26), fill=(90, 115, 140))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG", optimize=True)
    print("wrote %s (%d bytes, %dx%d)" % (OUT, OUT.stat().st_size, width, height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
