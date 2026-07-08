"""Generate the CricFloat app icon: a red cricket ball with a white seam on a
green rounded square, in macOS app-icon style.

    pip install pillow
    python tools/make_icon.py

Writes docs/icon_1024.png (the master) and docs/CricFloat.icns (used by
setup.py's py2app build). Requires macOS `iconutil` + `sips` for the .icns step.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

S = 1024
DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square background with a subtle vertical green gradient.
    pad = int(S * 0.06)
    box = [pad, pad, S - pad, S - pad]
    radius = int((S - 2 * pad) * 0.235)
    top, bot = (36, 126, 72), (17, 70, 42)
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=(
            int(top[0] * (1 - t) + bot[0] * t),
            int(top[1] * (1 - t) + bot[1] * t),
            int(top[2] * (1 - t) + bot[2] * t), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    cx, cy = S // 2, S // 2
    R = int(S * 0.27)

    # Soft drop shadow under the ball.
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - R, cy - R + 20, cx + R, cy + R + 20], fill=(0, 0, 0, 95))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))

    # Ball body + top-left highlight.
    ball = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ball).ellipse([cx - R, cy - R, cx + R, cy + R], fill=(170, 33, 39, 255))
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse(
        [cx - int(R * 0.75), cy - int(R * 0.75), cx + int(R * 0.1), cy + int(R * 0.1)],
        fill=(255, 255, 255, 55))
    ball.alpha_composite(hl.filter(ImageFilter.GaussianBlur(40)))
    img.alpha_composite(ball)

    # Centered double seam (two symmetric curved stitch rows).
    d = ImageDraw.Draw(img)
    for row_off in (-int(R * 0.17), int(R * 0.17)):
        n = 13
        for i in range(n):
            t = i / (n - 1)
            yy = cy - int(R * 0.80) + int(t * R * 1.60)
            bow = int(math.sin(t * math.pi) * R * 0.05)
            sx = cx + row_off + (bow if row_off > 0 else -bow)
            L = int(R * 0.14)
            d.line([(sx - L // 2, yy - 7), (sx + L // 2, yy + 7)],
                   fill=(246, 241, 231, 255), width=10)
    return img


def to_icns(png_path: str, icns_path: str) -> None:
    """macOS: build the .iconset (all required sizes) and pack it into .icns."""
    sizes = [
        (16, "icon_16x16"), (32, "icon_16x16@2x"),
        (32, "icon_32x32"), (64, "icon_32x32@2x"),
        (128, "icon_128x128"), (256, "icon_128x128@2x"),
        (256, "icon_256x256"), (512, "icon_256x256@2x"),
        (512, "icon_512x512"), (1024, "icon_512x512@2x"),
    ]
    with tempfile.TemporaryDirectory(suffix=".iconset") as iconset:
        for sz, name in sizes:
            subprocess.run(
                ["sips", "-z", str(sz), str(sz), png_path,
                 "--out", os.path.join(iconset, f"{name}.png")],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)


def main() -> None:
    os.makedirs(DOCS, exist_ok=True)
    png = os.path.join(DOCS, "icon_1024.png")
    icns = os.path.join(DOCS, "CricFloat.icns")
    draw_icon().save(png)
    to_icns(png, icns)
    print(f"wrote {png} and {icns}")


if __name__ == "__main__":
    main()
