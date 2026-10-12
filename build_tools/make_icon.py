"""Draws the app icon (a basketball on a dark navy tile) and writes an .icns file.

Usage: python build_tools/make_icon.py <out.icns>
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
# macOS icons sit inside a transparent margin: the tile is about 80% of the canvas.
TILE = (100, 100, 924, 924)
RADIUS = 185
TOP, BOTTOM = (23, 37, 84), (7, 11, 22)
BALL, BALL_SHADE, SEAM = (249, 115, 22), (194, 65, 12), (40, 16, 6)


def _gradient(top, bottom) -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(SIZE):
            px[x, y] = colour
    return img


def draw() -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(TILE, RADIUS, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(_gradient(TOP, BOTTOM), mask=mask)

    # The ball: orange, darker toward the bottom right, with black seams.
    c, r = SIZE // 2, 300
    box = (c - r, c - r, c + r, c + r)
    ball_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(ball_mask).ellipse(box, fill=255)
    shade = Image.new("RGB", (SIZE, SIZE))
    sp = shade.load()
    for y in range(c - r, c + r + 1):
        for x in range(c - r, c + r + 1):
            t = min(1.0, max(0.0, ((x - (c - r)) + (y - (c - r))) / (4 * r)))
            sp[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(BALL, BALL_SHADE))
    icon.paste(shade, mask=ball_mask)

    # Seams go on their own layer, clipped to the ball so the curves stop at its edge.
    w = 22
    seams = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(seams)
    d.line((c, c - r, c, c + r), fill=SEAM, width=w)
    d.line((c - r, c, c + r, c), fill=SEAM, width=w)
    # The two curved seams: arcs of larger circles centred off to each side.
    big = int(r * 1.15)
    d.arc((c - r - 2 * big + int(r * 0.55), c - big, c - r + int(r * 0.55), c + big), -90, 90, fill=SEAM, width=w)
    d.arc((c + r - int(r * 0.55), c - big, c + r + 2 * big - int(r * 0.55), c + big), 90, 270, fill=SEAM, width=w)
    clip = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    clip.paste(seams, mask=ball_mask)
    icon.alpha_composite(clip)
    ImageDraw.Draw(icon).ellipse(box, outline=SEAM, width=w)
    return icon


def main(out: str) -> None:
    icon = draw()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", out], check=True)
    icon.save(Path(out).with_suffix(".png"))


if __name__ == "__main__":
    main(sys.argv[1])
