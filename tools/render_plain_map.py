"""render_plain_map.py — the neutral theme's base render: a blank survey table.

The plain theme (Web/themes/plain.json) needs a backdrop that names no world:
an unseeded instance, or a dataset that brings no `meta.map_image` of its own,
is drawn on this. Parchment grain, a faint survey grid and a soft vignette;
no coastline, no labels, nothing anyone could recognise. 2048 x 2048 like the
other renders, so a dataset's percent positions mean the same thing on it.

Deterministic (fixed seed). Dev-time only: Pillow + numpy, never in the image.

    python tools/render_plain_map.py Web/static/map/plain.webp
"""
import sys

import numpy as np
from PIL import Image, ImageFilter

SIZE = 2048
PAPER = np.array([226, 214, 186], dtype=np.float32)
INK = np.array([120, 100, 70], dtype=np.float32)


def render(path):
    rng = np.random.default_rng(20261017)
    # grain: coarse blotches + fine tooth
    coarse = Image.fromarray((rng.random((64, 64)) * 255).astype(np.uint8), "L")
    coarse = np.asarray(coarse.resize((SIZE, SIZE), Image.BICUBIC), dtype=np.float32) / 255.0
    fine = rng.random((SIZE, SIZE)).astype(np.float32)
    tone = 0.75 * coarse + 0.25 * fine
    img = PAPER[None, None, :] * (0.94 + 0.08 * tone[..., None])

    # faint survey grid every 128 px, slightly heavier every 512 px
    grid = np.zeros((SIZE, SIZE), dtype=np.float32)
    for step, weight in ((128, 0.10), (512, 0.20)):
        grid[::step, :] = np.maximum(grid[::step, :], weight)
        grid[:, ::step] = np.maximum(grid[:, ::step], weight)
    grid = np.asarray(Image.fromarray((grid * 255).astype(np.uint8), "L")
                      .filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float32) / 255.0
    img = img * (1 - grid[..., None]) + INK[None, None, :] * grid[..., None]

    # vignette
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) / (SIZE - 1) - 0.5
    vig = np.clip(1.0 - 0.55 * (x * x + y * y) * 2.0, 0.0, 1.0)
    img = img * (0.80 + 0.20 * vig[..., None])

    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    out.save(path, "WEBP", quality=72, method=6)


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "Web/static/map/plain.webp")
