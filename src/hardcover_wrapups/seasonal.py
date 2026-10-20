"""Seasonal style: the grid layout with a border drawn for the time of year.

Everything here is drawn in code with Pillow: leaf outlines are hand-plotted points
or simple formulas, snowflakes and flowers are built from lines, ellipses and
polygons, all filled with gradients. No image files, no generated art.
"""
import functools
import math
import random

from PIL import Image, ImageDraw

from .render import grid_layout, grid_tiles, load_font, paste_shadowed, paste_tiles

SUPERSAMPLE = 4  # Pillow doesn't anti-alias shapes, so draw big and shrink

THEME_NAMES = ["autumn", "winter", "spring", "summer"]


def theme_for_month(month):
    """The season a month falls in, in the northern hemisphere."""
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(month, "autumn")


# ------------------------------------------------------------- Helpers ----

def blank(size):
    """A transparent square to draw a sprite on, SUPERSAMPLE times bigger than `size`."""
    return Image.new("RGBA", (size * SUPERSAMPLE,) * 2, (0, 0, 0, 0))


def finish(img, size):
    return img.resize((size, size), Image.LANCZOS)


def mix(a, b, t):
    return tuple(int(a[k] * (1 - t) + b[k] * t) for k in range(3))


def vertical_gradient(width, height, top, bottom):
    strip = Image.new("RGB", (1, 256))
    for i in range(256):
        strip.putpixel((0, i), mix(top, bottom, i / 255))
    return strip.resize((width, height), Image.BILINEAR)


@functools.lru_cache(maxsize=64)
def _radial(inner, outer):
    small = Image.new("RGB", (64, 64))
    for y in range(64):
        for x in range(64):
            r = min(1.0, math.hypot(x - 31.5, y - 31.5) / 32)
            small.putpixel((x, y), mix(inner, outer, r))
    return small


def radial_gradient(size, inner, outer):
    """A square fading from `inner` at the centre to `outer` at the edge."""
    return _radial(inner, outer).resize((size, size), Image.BILINEAR)


def rotate_point(x, y, angle):
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


# -------------------------------------------------------------- Leaves ----

# Right half of a maple leaf, from the tip of the top lobe down to the stem,
# with y pointing up; mirrored for the left half.
MAPLE_RIGHT = [
    (0.00, 1.00), (0.08, 0.88), (0.16, 0.92), (0.17, 0.78), (0.25, 0.76), (0.10, 0.52),
    (0.30, 0.62), (0.36, 0.74), (0.44, 0.64), (0.64, 0.80), (0.58, 0.58), (0.72, 0.52),
    (0.52, 0.42), (0.62, 0.32), (0.20, 0.28),
    (0.40, 0.20), (0.46, 0.08), (0.26, 0.12), (0.06, 0.06),
    (0.025, 0.05), (0.02, -0.20),
]
# Where the maple's main veins end: the lobe tips.
MAPLE_VEINS = [(0.0, 1.0), (0.64, 0.80), (-0.64, 0.80), (0.46, 0.08), (-0.46, 0.08)]


def maple_outline():
    return MAPLE_RIGHT + [(-x, y) for x, y in reversed(MAPLE_RIGHT)]


def lobed_half(width, lobes, depth, phase, points=90):
    """One side of a leaf along a midrib from y=0 to y=1, with rounded lobes."""
    half = []
    for i in range(points + 1):
        t = i / points
        w = width * math.sin(math.pi * t) ** 0.7 * (0.75 + 0.25 * t)
        if lobes:
            w *= 1 - depth + depth * abs(math.sin(math.pi * lobes * t + phase)) ** 0.45
        half.append((w, t))
    return half


def leaf_outline(width, lobes=0, depth=0):
    right = [(0.02, -0.18), (0.02, 0.0)] + lobed_half(width, lobes, depth, 0)
    # offsetting the left side's lobes makes them alternate, like a real oak leaf
    left = [(-x, y) for x, y in lobed_half(width, lobes, depth, 0.9 if lobes else 0)]
    return right + left[::-1] + [(-0.02, 0.0), (-0.02, -0.18)]


def side_veins(pairs, reach=0.2):
    ends = []
    for i in range(pairs):
        t = 0.2 + 0.62 * i / max(1, pairs - 1)
        r = reach * math.sin(math.pi * t) ** 0.7
        ends += [((0, t), (r, t + 0.08)), ((0, t), (-r, t + 0.08))]
    return ends


LEAF_SHAPES = {
    "maple": lambda: (maple_outline(), [((0, 0.1), end) for end in MAPLE_VEINS]),
    "oak": lambda: (leaf_outline(0.34, 4.5, 0.55), [((0, 0), (0, 0.95))] + side_veins(4)),
    "beech": lambda: (leaf_outline(0.26), [((0, 0), (0, 0.97))] + side_veins(5)),
}


def leaf_sprite(shape, size, colors):
    """A leaf `size` pixels tall, pointing up, filled with a base-to-tip gradient."""
    img = blank(size)
    s = img.width
    outline, veins = LEAF_SHAPES[shape]()

    def to_px(x, y):  # leaf space (stem at y=-0.2, tip at y=1) to pixels
        return (s / 2 + x * s * 0.68, s * 0.94 - (y + 0.2) * s * 0.68)

    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon([to_px(x, y) for x, y in outline], fill=255)
    light, dark = colors
    leaf = vertical_gradient(s, s, dark, light).convert("RGBA")
    d = ImageDraw.Draw(leaf)
    vein = tuple(int(c * 0.72) for c in dark)
    for start, end in veins:
        d.line([to_px(*start), to_px(*end)], fill=vein, width=max(1, int(s * 0.012)))
    leaf.putalpha(mask)
    return finish(leaf, size)


# ---------------------------------------------------------- Snowflakes ----

def snowflake_sprite(size, color, rng):
    """A six-armed snowflake with randomly chosen (but symmetric) side branches."""
    img = blank(size)
    s = img.width
    d = ImageDraw.Draw(img)
    c, arm = s / 2, s * 0.46
    width = max(2, int(s * rng.uniform(0.03, 0.045)))
    branches = [(rng.uniform(0.3, 0.8), rng.uniform(0.15, 0.32)) for _ in range(rng.randint(1, 3))]
    fill = color + (255,)
    for k in range(6):
        a = math.pi / 3 * k
        tip = (c + arm * math.cos(a), c + arm * math.sin(a))
        d.line([(c, c), tip], fill=fill, width=width)
        d.ellipse([tip[0] - width, tip[1] - width, tip[0] + width, tip[1] + width], fill=fill)
        for at, length in branches:
            bx, by = c + arm * at * math.cos(a), c + arm * at * math.sin(a)
            for side in (-1, 1):
                b = a + side * math.pi / 3
                d.line([(bx, by), (bx + arm * length * math.cos(b), by + arm * length * math.sin(b))],
                       fill=fill, width=width)
    hexagon = [(c + s * 0.06 * math.cos(math.pi / 3 * k + math.pi / 6),
                c + s * 0.06 * math.sin(math.pi / 3 * k + math.pi / 6)) for k in range(6)]
    d.polygon(hexagon, fill=fill)
    return finish(img, size)


def snow_dot_sprite(size, color):
    img = blank(size)
    s = img.width
    ImageDraw.Draw(img).ellipse([s * 0.3, s * 0.3, s * 0.7, s * 0.7], fill=color + (235,))
    return finish(img, size)


# ------------------------------------------------------------- Flowers ----

def petal_points(c, length, width, notch, angle):
    """Outline of one petal from the centre (c, c) outward, rotated by `angle` radians."""
    pts = []
    for i in range(41):
        t = math.pi * i / 40  # half an ellipse, from one side of the base round the tip
        x, y = width / 2 * math.cos(t), -length / 2 - length / 2 * math.sin(t)
        if notch and i == 20:  # cherry petals have a little notch at the tip
            pts += [(width * 0.12, y), (0, y + length * 0.13), (-width * 0.12, y)]
            continue
        pts.append((x, y))
    pts += [(-width / 2 * 0.3, -length * 0.15), (0, 0), (width / 2 * 0.3, -length * 0.15)]
    return [(c + px, c + py) for px, py in (rotate_point(x, y, angle) for x, y in pts)]


def flower_sprite(size, petals, petal_colors, center_colors, length, width, notch, rng,
                  stamens=False):
    img = blank(size)
    s = img.width
    c = s / 2
    tilt = rng.uniform(0, 360)
    petal_fill = radial_gradient(s, petal_colors[1], petal_colors[0]).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    for k in range(petals):
        angle = math.radians(tilt + 360 / petals * k)
        md.polygon(petal_points(c, length * s, width * s, notch, angle), fill=255)
    petal_fill.putalpha(mask)
    img.alpha_composite(petal_fill)

    d = ImageDraw.Draw(img)
    if stamens:
        for k in range(10):
            a = math.radians(tilt + 36 * k + 12)
            end = (c + s * 0.16 * math.cos(a), c + s * 0.16 * math.sin(a))
            d.line([(c, c), end], fill=center_colors[1] + (255,), width=max(1, s // 120))
            r = s * 0.014
            d.ellipse([end[0] - r, end[1] - r, end[0] + r, end[1] + r], fill=center_colors[0] + (255,))
    r = s * (0.06 if stamens else 0.12)
    centre = radial_gradient(int(2 * r), center_colors[0], center_colors[1]).convert("RGBA")
    round_mask = Image.new("L", centre.size, 0)
    ImageDraw.Draw(round_mask).ellipse([0, 0, centre.width - 1, centre.height - 1], fill=255)
    img.paste(centre, (int(c - r), int(c - r)), round_mask)
    if not stamens:  # daisy: a few seed dots in the middle
        for _ in range(14):
            a, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0, r * 0.7)
            x, y = c + dist * math.cos(a), c + dist * math.sin(a)
            d.ellipse([x - s * 0.008, y - s * 0.008, x + s * 0.008, y + s * 0.008],
                      fill=center_colors[1] + (255,))
    return finish(img, size)


def loose_petal_sprite(size, colors):
    img = blank(size)
    s = img.width
    fill = radial_gradient(s, colors[1], colors[0]).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    pts = petal_points(s / 2, s * 0.84, s * 0.6, True, 0)
    ImageDraw.Draw(mask).polygon([(x, y + s * 0.42) for x, y in pts], fill=255)  # centred
    fill.putalpha(mask)
    return finish(fill, size)


def citrus_sprite(size, rind, flesh):
    """A slice of citrus: rind, pith and wedge-shaped segments."""
    img = blank(size)
    s = img.width
    d = ImageDraw.Draw(img)
    c, r = s / 2, s * 0.46
    d.ellipse([c - r, c - r, c + r, c + r], fill=rind + (255,))
    pith = (252, 248, 232)
    d.ellipse([c - r * 0.9, c - r * 0.9, c + r * 0.9, c + r * 0.9], fill=pith + (255,))
    segments = 9
    for k in range(segments):
        a0 = 2 * math.pi * k / segments + 0.07
        a1 = 2 * math.pi * (k + 1) / segments - 0.07
        inner = r * 0.08
        pts = [(c + inner * math.cos((a0 + a1) / 2), c + inner * math.sin((a0 + a1) / 2))]
        pts += [(c + r * 0.8 * math.cos(a0 + (a1 - a0) * i / 12),
                 c + r * 0.8 * math.sin(a0 + (a1 - a0) * i / 12)) for i in range(13)]
        d.polygon(pts, fill=flesh + (255,))
    shine = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shine).ellipse([c - r * 0.55, c - r * 0.62, c - r * 0.1, c - r * 0.35],
                                  fill=(255, 255, 255, 70))
    img.alpha_composite(shine)
    return finish(img, size)


# -------------------------------------------------------------- Themes ----

AUTUMN_LEAVES = [
    ((214, 72, 38), (168, 44, 30)),     # red
    ((232, 122, 40), (196, 78, 32)),    # orange
    ((238, 178, 56), (214, 128, 40)),   # gold
    ((170, 96, 48), (122, 62, 34)),     # brown
    ((200, 140, 50), (150, 92, 36)),    # ochre
]
SPRING_LEAVES = [((150, 200, 90), (96, 160, 64)), ((176, 214, 110), (120, 178, 72))]
SUMMER_LEAVES = [((96, 170, 72), (54, 120, 52)), ((130, 190, 84), (78, 146, 60))]


def autumn_piece(rng):
    shape = rng.choices(["maple", "oak", "beech"], weights=[5, 3, 2])[0]
    return leaf_sprite(shape, rng.randint(70, 135), rng.choice(AUTUMN_LEAVES)), True


def winter_piece(rng):
    if rng.random() < 0.3:
        return snow_dot_sprite(rng.randint(14, 30), (255, 255, 255)), False
    color = rng.choice([(255, 255, 255), (232, 242, 252), (196, 220, 244)])
    return snowflake_sprite(rng.randint(55, 125), color, rng), True


def spring_piece(rng):
    roll = rng.random()
    if roll < 0.55:
        petals = rng.choice([((252, 214, 228), (238, 150, 182)), ((255, 240, 245), (246, 192, 212))])
        return flower_sprite(rng.randint(60, 115), 5, petals, ((255, 214, 90), (210, 80, 120)),
                             0.42, 0.34, True, rng, stamens=True), False
    if roll < 0.8:
        return leaf_sprite("beech", rng.randint(55, 100), rng.choice(SPRING_LEAVES)), True
    return loose_petal_sprite(rng.randint(28, 48), ((252, 214, 228), (240, 160, 190))), True


def summer_piece(rng):
    roll = rng.random()
    if roll < 0.45:
        return flower_sprite(rng.randint(70, 125), rng.choice([16, 18, 20]),
                             ((255, 255, 255), (240, 236, 222)), ((250, 196, 40), (196, 120, 20)),
                             0.44, 0.1, False, rng), False
    if roll < 0.75:
        rind, flesh = rng.choice([((238, 132, 30), (255, 178, 70)),     # orange
                                  ((236, 204, 40), (255, 232, 120)),    # lemon
                                  ((104, 168, 48), (184, 222, 110))])   # lime
        return citrus_sprite(rng.randint(60, 105), rind, flesh), True
    return leaf_sprite("beech", rng.randint(60, 105), rng.choice(SUMMER_LEAVES)), True


THEMES = {
    "autumn": {"background": ((252, 246, 234), (244, 230, 207)), "piece": autumn_piece,
               "banner": (255, 251, 242), "banner_edge": (196, 128, 70), "text": (92, 46, 22)},
    "winter": {"background": ((222, 236, 248), (190, 214, 238)), "piece": winter_piece,
               "banner": (255, 255, 255), "banner_edge": (120, 160, 206), "text": (32, 58, 98)},
    "spring": {"background": ((252, 243, 246), (234, 244, 226)), "piece": spring_piece,
               "banner": (255, 252, 253), "banner_edge": (226, 150, 182), "text": (108, 46, 78)},
    "summer": {"background": ((222, 242, 252), (252, 244, 214)), "piece": summer_piece,
               "banner": (255, 254, 248), "banner_edge": (236, 160, 60), "text": (30, 84, 110)},
}


# ------------------------------------------------------------ Rendering ----

def scatter_border(canvas, rng, piece, band, step=72):
    """Scatter decorations along all four edges, some running off the edge."""
    w, h = canvas.size

    def inward():
        return rng.uniform(-10, band * 0.55)

    spots = []
    for x in range(0, w + step, step):
        spots += [(x + rng.uniform(-24, 24), inward()), (x + rng.uniform(-24, 24), h - inward())]
    for y in range(step // 2, h, step):
        spots += [(inward(), y + rng.uniform(-24, 24)), (w - inward(), y + rng.uniform(-24, 24))]
    for cx, cy in [(0, 0), (w, 0), (0, h), (w, h)]:  # fuller corners
        spots += [(cx + rng.uniform(-30, 30) * (1 if cx == 0 else -1),
                   cy + rng.uniform(-30, 30) * (1 if cy == 0 else -1)) for _ in range(3)]
    rng.shuffle(spots)

    for x, y in spots:
        sprite, rotate = piece(rng)
        if rotate:
            sprite = sprite.rotate(rng.uniform(0, 360), expand=True, resample=Image.BICUBIC)
        paste_shadowed(canvas, sprite, (int(x) - sprite.width // 2, int(y) - sprite.height // 2),
                       blur=3, offset=(2, 3), opacity=60)


def render_seasonal(books, title, out_path, columns=4, theme="autumn", seed=0, cover_w=300):
    theme = THEMES[theme]
    rng = random.Random(seed)
    gap, margin, header_h = 22, 110, 150
    tiles = grid_tiles(books, cover_w)
    placed, grid_w, bottom = grid_layout(tiles, columns, cover_w, gap, margin, margin + header_h)
    width, height = 2 * margin + grid_w, bottom + margin

    canvas = vertical_gradient(width, height, *theme["background"]).convert("RGBA")
    scatter_border(canvas, rng, theme["piece"], band=margin)
    paste_tiles(canvas, placed, opacity=80)

    # title banner
    f = load_font(50)
    tw = int(ImageDraw.Draw(canvas).textlength(title, font=f))
    bw, bh = min(width - 2 * margin, tw + 120), 96
    banner = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(banner)
    bd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=22, fill=theme["banner"] + (255,),
                         outline=theme["banner_edge"] + (255,), width=3)
    bd.text(((bw - tw) / 2, (bh - 50) / 2 - 6), title, font=f, fill=theme["text"])
    paste_shadowed(canvas, banner, ((width - bw) // 2, margin + 10), blur=6, offset=(0, 5), opacity=80)

    canvas.convert("RGB").save(out_path, format="PNG")
