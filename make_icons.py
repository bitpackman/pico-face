#!/usr/bin/env python3
"""Generate pi-face PWA icons (192/512 + maskable) with PIL."""
from PIL import Image, ImageDraw

BG = (10, 14, 20)
EYE = (110, 231, 255)


def draw_face(size, pad_ratio):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # rounded-square background
    r = size * 0.22
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    pad = size * pad_ratio          # extra padding for maskable safe zone
    s = size - pad * 2              # face area
    ew, eh = s * 0.20, s * 0.26     # eye size
    gap = s * 0.14
    cy = pad + s * 0.42
    for cx in (pad + s / 2 - gap / 2 - ew, pad + s / 2 + gap / 2):
        d.rounded_rectangle([cx, cy - eh / 2, cx + ew, cy + eh / 2],
                            radius=ew * 0.45, fill=EYE)
        # sparkle highlights
        hw = ew * 0.36
        d.ellipse([cx + ew * 0.14, cy - eh * 0.36,
                   cx + ew * 0.14 + hw, cy - eh * 0.36 + hw * 0.8], fill="white")
        hw2 = ew * 0.16
        d.ellipse([cx + ew * 0.58, cy + eh * 0.05,
                   cx + ew * 0.58 + hw2, cy + eh * 0.05 + hw2], fill="white")
    # little smile
    mw, mh = s * 0.16, s * 0.09
    mx, my = pad + s / 2 - mw / 2, pad + s * 0.62
    d.arc([mx, my - mh, mx + mw, my + mh], start=20, end=160,
          fill=EYE, width=max(2, int(size * 0.02)))
    return img


for size in (192, 512):
    draw_face(size, 0.10).save(f"icon-{size}.png")
draw_face(512, 0.20).save("icon-maskable-512.png")
print("icons written")
