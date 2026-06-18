"""Generate the tray icon image in different states, using Pillow.

Kept separate from tray.py so the icon can be rendered/tested without a running
system tray, and so tray.py stays focused on menu/state wiring.
"""

from __future__ import annotations

STATE_COLORS = {
    "idle": (52, 120, 246),       # blue
    "working": (245, 166, 35),    # amber
    "attention": (224, 64, 64),   # red
    "paused": (140, 140, 140),    # grey
}


def make_icon(state: str = "idle", size: int = 64):
    from PIL import Image, ImageDraw

    color = STATE_COLORS.get(state, STATE_COLORS["idle"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded-square background
    pad = 4
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=12, fill=color)

    # inbox tray glyph: a shallow tray with a down-arrow dropping into it
    w = size
    cx = w / 2
    tray_top = w * 0.58
    tray_bottom = w * 0.72
    left = w * 0.28
    right = w * 0.72
    white = (255, 255, 255, 255)

    # arrow shaft
    d.line([(cx, w * 0.26), (cx, w * 0.5)], fill=white, width=5)
    # arrow head
    d.polygon([(cx - 8, w * 0.46), (cx + 8, w * 0.46), (cx, w * 0.57)], fill=white)
    # tray
    d.line([(left, tray_top), (left, tray_bottom), (right, tray_bottom), (right, tray_top)],
           fill=white, width=5, joint="curve")
    return img
