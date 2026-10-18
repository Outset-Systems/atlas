"""render_plain_map.py — the neutral theme's base render: a blank survey table.

The plain theme (Web/themes/plain.json) needs a backdrop that names no world:
an unseeded instance, or a dataset that brings no `meta.map_image` of its own,
is drawn on this. It is the demo lab's sand table (demo-lab/build.py
`render_base`) with nothing on it yet: dark sand under one pool of light, raked
in rings, a faint survey grid pressed in, the edges falling away to the page's
abyss. the design notes's app is dark-only, so the pale labels must read on it; the
first cut was pale parchment and nothing did (2026-10-18). No coastline, no
labels, nothing anyone could recognise. 2048 x 2048 like the other renders, so
a dataset's percent positions mean the same thing on it.

Deterministic (fixed seed). Dev-time only: Pillow + numpy, never in the image.

    python tools/render_plain_map.py Web/static/map/plain.webp
"""
import sys

import numpy as np
from PIL import Image, ImageFilter

SIZE = 2048
SAND = np.array([100, 80, 58], dtype=np.float32)      # demo-lab render_base's ground
GROOVE = np.array([62, 49, 35], dtype=np.float32)     # the grid, pressed in
ABYSS = np.array([13, 11, 7], dtype=np.float32)       # --abyss #0D0B07


def render(path):
    rng = np.random.default_rng(20261017)
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) / (SIZE - 1)
    coarse = Image.fromarray((rng.random((48, 48)) * 255).astype(np.uint8), "L")
    coarse = np.asarray(coarse.resize((SIZE, SIZE), Image.BICUBIC), dtype=np.float32) / 255.0
    grain = rng.random((SIZE, SIZE)).astype(np.float32)

    # dark sand under one pool of light, raked in rings around the table
    light = np.exp(-(((x - 0.44) ** 2) + ((y - 0.42) ** 2)) / (2 * 0.32 ** 2))
    r = np.sqrt((x - 0.5) ** 2 + (y - 0.48) ** 2) + 0.004 * (coarse - 0.5)
    rings = np.sin(r * 2 * np.pi * 60)
    tone = 0.50 + 0.45 * light + 0.06 * rings + 0.04 * (coarse - 0.5) + 0.03 * (grain - 0.5)
    img = SAND[None, None, :] * tone[..., None]

    # a faint survey grid every 128 px, slightly deeper every 512 px
    grid = np.zeros((SIZE, SIZE), dtype=np.float32)
    for step, weight in ((128, 0.10), (512, 0.22)):
        grid[::step, :] = np.maximum(grid[::step, :], weight)
        grid[:, ::step] = np.maximum(grid[:, ::step], weight)
    grid = np.asarray(Image.fromarray((grid * 255).astype(np.uint8), "L")
                      .filter(ImageFilter.GaussianBlur(1.0)), dtype=np.float32) / 255.0
    grid = grid * (0.55 + 0.45 * light)                 # it fades with the light
    img = img * (1 - grid[..., None]) + GROOVE[None, None, :] * grid[..., None]

    # the edges fall away to the page
    d = np.sqrt((x - 0.5) ** 2 + (y - 0.5) ** 2)
    vig = np.clip((d - 0.30) / 0.42, 0.0, 1.0)[..., None]
    img = img * (1 - 0.85 * vig) + ABYSS * 0.85 * vig

    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    out.save(path, "WEBP", quality=72, method=6)


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "Web/static/map/plain.webp")
