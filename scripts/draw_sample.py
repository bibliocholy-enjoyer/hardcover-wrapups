"""Draw the landing page's sample wrap-up from made-up books with covers drawn in code.

Run from the repo root:  uv run python scripts/draw_sample.py

Writes src/hardcover_wrapups/static/sample.jpg. No real books or covers are used, so the
sample can be shown publicly without anyone's artwork.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from hardcover_wrapups import render, seasonal

STATIC = Path(__file__).resolve().parent.parent / "src" / "hardcover_wrapups" / "static"
W, H = 600, 900  # cover size before the renderer scales it

BOOKS = [
    ("The Lighthouse at Wren Hollow", "Mara Ellison", "2026-10-03"),
    ("Small Engines of Joy", "Theo Park", "2026-10-06"),
    ("A Field Guide to Quiet", "June Okafor", "2026-10-09"),
    ("The Cartographer's Tea", "Ines Varga", "2026-10-13"),
    ("Orbit of Pears", "Sam Holloway", "2026-10-17"),
    ("Night Train to Ostra", "Lena Brandt", "2026-10-21"),
    ("Paper Moons over Kettle Bay", "Rosa Delgado", "2026-10-25"),
    ("How to Grow a Thunderstorm", "Felix Moreau", "2026-10-29"),
]


def gradient(top, bottom):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(top, bottom)))
    return img


def lighthouse(rng):
    img = gradient((36, 52, 104), (238, 150, 110))
    d = ImageDraw.Draw(img)
    d.ellipse([400, 330, 500, 430], fill=(255, 236, 190))                   # moon
    d.polygon([(250, 820), (350, 820), (330, 480), (270, 480)], fill=(245, 240, 232))
    for y in (560, 660, 760):                                               # stripes
        d.polygon([(268 - (y - 480) * 0.06, y), (332 + (y - 480) * 0.06, y),
                   (334 + (y - 480) * 0.06, y + 40), (266 - (y - 480) * 0.06, y + 40)], fill=(200, 60, 54))
    d.rectangle([262, 440, 338, 480], fill=(250, 214, 110))                 # lamp room
    d.polygon([(255, 440), (345, 440), (300, 400)], fill=(60, 50, 60))
    d.polygon([(338, 450), (600, 380), (600, 520)], fill=(255, 240, 180))   # beam
    for y in range(820, 900, 18):                                           # waves
        d.line([(0, y), (W, y)], fill=(40, 70, 120), width=8)
    return img, (255, 250, 240)


def stripes(rng):
    img = Image.new("RGB", (W, H), (250, 236, 210))
    d = ImageDraw.Draw(img)
    colors = [(232, 94, 60), (246, 176, 60), (60, 150, 140), (40, 60, 90)]
    for k in range(-8, 14):
        x = k * 70
        d.polygon([(x, H), (x + 35, H), (x + 35 + 500, 300), (x + 500, 300)], fill=colors[k % 4])
    d.rectangle([0, 0, W, 300], fill=(250, 236, 210))
    return img, (40, 40, 60)


def quiet(rng):
    img = Image.new("RGB", (W, H), (226, 232, 220))
    d = ImageDraw.Draw(img)
    d.ellipse([110, 380, 490, 760], fill=(126, 160, 132))
    for _ in range(40):
        x, y, r = rng.randint(30, 570), rng.randint(330, 860), rng.randint(3, 7)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(70, 100, 80))
    return img, (40, 60, 50)


def map_cover(rng):
    img = Image.new("RGB", (W, H), (240, 226, 196))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(214, 196, 160), width=2)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(214, 196, 160), width=2)
    pts = [(80, 820), (160, 700), (300, 740), (360, 600), (480, 560), (440, 420)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        steps = int(math.hypot(x2 - x1, y2 - y1) // 18)
        for i in range(0, steps, 2):
            a, b = i / steps, (i + 1) / steps
            d.line([(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)],
                   fill=(170, 60, 50), width=6)
    d.line([(420, 400), (460, 440)], fill=(170, 60, 50), width=10)
    d.line([(460, 400), (420, 440)], fill=(170, 60, 50), width=10)
    d.ellipse([360, 330 - 10, 520, 330 + 10], fill=(214, 196, 160))
    return img, (90, 50, 30)


def orbits(rng):
    img = Image.new("RGB", (W, H), (34, 38, 66))
    d = ImageDraw.Draw(img)
    cx, cy = 300, 600
    for r in (90, 160, 230):
        d.ellipse([cx - r, cy - r * 0.55, cx + r, cy + r * 0.55], outline=(120, 130, 190), width=3)
    d.ellipse([cx - 45, cy - 45, cx + 45, cy + 45], fill=(246, 196, 80))
    for r, a in ((90, 0.6), (160, 2.4), (230, 4.4)):
        x, y = cx + r * math.cos(a), cy + r * 0.55 * math.sin(a)
        d.ellipse([x - 22, y - 14, x + 22, y + 30], fill=(170, 200, 90))    # a pear: body
        d.ellipse([x - 14, y - 34, x + 14, y - 4], fill=(170, 200, 90))     # and neck
    return img, (240, 236, 250)


def night_train(rng):
    img = gradient((14, 20, 44), (60, 40, 80))
    d = ImageDraw.Draw(img)
    for _ in range(70):
        x, y = rng.randint(0, W), rng.randint(300, 620)
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 250, 220))
    d.polygon([(0, 900), (600, 900), (330, 640), (270, 640)], fill=(40, 34, 50))
    d.line([(150, 900), (292, 640)], fill=(190, 180, 200), width=6)
    d.line([(450, 900), (308, 640)], fill=(190, 180, 200), width=6)
    for k in range(9):
        t = (k / 9) ** 1.6
        y = 900 - t * 260
        half = 150 - t * 140
        d.line([(300 - half, y), (300 + half, y)], fill=(110, 100, 120), width=max(2, int(10 * (1 - t))))
    d.ellipse([288, 628, 312, 652], fill=(255, 226, 140))                   # the train's light
    return img, (240, 230, 255)


def moons(rng):
    img = Image.new("RGB", (W, H), (36, 76, 110))
    d = ImageDraw.Draw(img)
    for row in range(5):
        for col in range(4):
            x, y = 75 + col * 150, 360 + row * 120
            d.ellipse([x - 40, y - 40, x + 40, y + 40], fill=(246, 230, 190))
            d.ellipse([x - 22, y - 46, x + 58, y + 34], fill=(36, 76, 110))
    return img, (246, 230, 190)


def thunderstorm(rng):
    img = Image.new("RGB", (W, H), (180, 214, 230))
    d = ImageDraw.Draw(img)
    for cx, cy, r in [(220, 480, 110), (330, 440, 130), (430, 500, 100), (300, 540, 120)]:
        d.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=(120, 130, 150))
    d.polygon([(320, 600), (260, 740), (310, 740), (270, 880), (380, 700), (325, 700), (370, 600)],
              fill=(250, 210, 60))
    d.rectangle([260, 860, 340, 900], fill=(170, 110, 70))                  # a flower pot
    return img, (30, 50, 70)


ARTWORK = [lighthouse, stripes, quiet, map_cover, orbits, night_train, moons, thunderstorm]


def make_cover(title, author, art, rng):
    img, ink = art(rng)
    d = ImageDraw.Draw(img)
    title_font, author_font = render.load_font(52), render.load_font(30)
    y = 70
    for line in render.wrap(d, title, title_font, W - 100):
        d.text((50, y), line, font=title_font, fill=ink)
        y += 64
    d.text((50, y + 14), author.upper(), font=author_font, fill=ink)
    return img


def main():
    rng = random.Random(7)
    books = []
    for (title, author, finished), art in zip(BOOKS, ARTWORK):
        books.append({"title": title, "authors": [author], "finished": finished, "started": "",
                      "image": make_cover(title, author, art, rng)})
    out = STATIC / "sample.png"
    seasonal.render_seasonal(books, render.make_title(2026, 10), out, columns=4, theme="autumn")
    img = Image.open(out)
    img = img.resize((900, round(img.height * 900 / img.width)), Image.LANCZOS)
    img.save(STATIC / "sample.jpg", quality=86, optimize=True, progressive=True)
    out.unlink()
    print(f"wrote {STATIC / 'sample.jpg'} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
