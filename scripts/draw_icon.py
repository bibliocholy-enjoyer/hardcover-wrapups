"""Draw the app icon (a calendar page with book spines) in code, at every size we need.

Run from the repo root:  uv run python scripts/draw_icon.py

Writes PNGs and favicon.ico into src/hardcover_wrapups/static/. Sizes of 32 px and
below use a simpler drawing (three thick spines) that stays readable that small.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

STATIC = Path(__file__).resolve().parent.parent / "src" / "hardcover_wrapups" / "static"
N = 2048  # draw big, then shrink: Pillow doesn't anti-alias shapes

PURPLE_TOP, PURPLE_BOTTOM = (112, 96, 222), (72, 58, 178)
RED, ORANGE, GOLD, TEAL, PURPLE = (222, 78, 52), (240, 140, 52), (246, 190, 64), (38, 168, 160), (112, 96, 222)
WHITE, RINGS, SHELF = (255, 255, 255), (70, 60, 90), (200, 190, 210)


def px(fraction):
    return int(N * fraction)


def background():
    strip = Image.new("RGB", (1, 256))
    for i in range(256):
        t = i / 255
        strip.putpixel((0, i), tuple(int(a * (1 - t) + b * t) for a, b in zip(PURPLE_TOP, PURPLE_BOTTOM)))
    bg = strip.resize((N, N)).convert("RGBA")
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, N - 1, N - 1], radius=px(0.22), fill=255)
    bg.putalpha(mask)
    return bg


def add_with_shadow(base, layer):
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda a: a * 110 // 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(40))
    base.alpha_composite(shadow, (0, 30))
    base.alpha_composite(layer)


def draw_icon(simple=False):
    """The calendar page full of books. `simple` drops detail for tiny sizes."""
    img = background()
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = px(0.16), px(0.2), px(0.84), px(0.82)
    r = px(0.06)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=WHITE + (255,))
    head = px(0.2 if simple else 0.17)
    d.rounded_rectangle([x0, y0, x1, y0 + head], radius=r, fill=RED + (255,))
    d.rectangle([x0, y0 + head - r, x1, y0 + head], fill=RED + (255,))
    if not simple:  # binder rings
        for rx in (x0 + (x1 - x0) * 3 // 10, x0 + (x1 - x0) * 7 // 10):
            d.rounded_rectangle([rx - px(0.025), y0 - px(0.06), rx + px(0.025), y0 + px(0.05)],
                                radius=px(0.025), fill=RINGS + (255,))

    shelf = y1 - px(0.08)
    if simple:
        spines, gap = [(TEAL, 0.38, 0.13), (GOLD, 0.32, 0.11), (RED, 0.40, 0.13)], px(0.04)
    else:
        spines, gap = [(TEAL, 0.36, 0.085), (GOLD, 0.30, 0.07), (RED, 0.40, 0.09),
                       (ORANGE, 0.33, 0.075), (PURPLE, 0.38, 0.08)], px(0.018)
        d.rectangle([x0 + px(0.05), shelf, x1 - px(0.05), shelf + px(0.018)], fill=SHELF + (255,))
    x = (N - sum(px(w) for _, _, w in spines) - gap * (len(spines) - 1)) // 2
    for color, height, width in spines:
        w, h = px(width), px(height)
        d.rounded_rectangle([x, shelf - h, x + w, shelf], radius=px(0.012), fill=color + (255,))
        if not simple:  # light bands across each spine
            band = tuple(min(255, c + 60) for c in color) + (255,)
            d.rectangle([x, shelf - h * 80 // 100, x + w, shelf - h * 74 // 100], fill=band)
            d.rectangle([x, shelf - h * 26 // 100, x + w, shelf - h * 20 // 100], fill=band)
        x += w + gap
    add_with_shadow(img, layer)
    return img


def main():
    full, simple = draw_icon(), draw_icon(simple=True)

    def sized(size):
        return (simple if size <= 32 else full).resize((size, size), Image.LANCZOS)

    for name, size in [("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180),
                       ("favicon-32.png", 32)]:
        sized(size).save(STATIC / name, optimize=True)
    sized(48).save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=[sized(16), sized(32)])
    print(f"wrote icons to {STATIC}")


if __name__ == "__main__":
    main()
