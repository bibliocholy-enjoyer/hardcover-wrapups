#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""Make a StoryGraph-style monthly wrap-up cover collage from your Hardcover library.

Setup:
    export HARDCOVER_TOKEN="hc_pat_..."

Usage (uv installs pillow automatically):
    uv run hc_wrapup.py 8 2026
    uv run hc_wrapup.py august 2026 --columns 5 --name "Sam's"
    uv run hc_wrapup.py 8 2026 --style shelf   # bookshelf
    uv run hc_wrapup.py 8 2026 --style cork    # corkboard
    uv run hc_wrapup.py 8 2026 --style calendar  # covers on the day you finished them
    uv run hc_wrapup.py 8 2026 --style rainbow   # sorted by cover colour
    uv run hc_wrapup.py 8 2026 --style eight     # covers arranged in a figure 8
    uv run hc_wrapup.py 8 2026 --debug        # print what the API returned
"""
import argparse
import calendar
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

from PIL import Image, ImageDraw, ImageFilter, ImageFont

API_URL = "https://api.hardcover.app/v1/graphql"

# Ways Hardcover might expose the cover image; we try each until one is accepted.
IMAGE_FIELDS = ["image { url }", "cached_image"]

ME_QUERY = "query { me { id username } }"

BOOKS_QUERY = """
query ($uid: Int!, $start: date!, $end: date!) {
  user_books(where: {
    user_id: {_eq: $uid},
    user_book_reads: {finished_at: {_gte: $start, _lt: $end}}
  }) {
    user_book_reads(
      where: {finished_at: {_gte: $start, _lt: $end}},
      order_by: {finished_at: asc}
    ) { started_at finished_at }
    book {
      title
      %IMAGE%
      contributions { author { name } }
    }
  }
}
"""


# ---------------------------------------------------------------- API ----

def gql(token, query, variables=None):
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Content-Type": "application/json",
            "authorization": auth,
            "User-Agent": "hc-wrapup-script/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from Hardcover: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")


def first(x):
    """`me` comes back as a list in Hardcover's API; tolerate a plain object too."""
    return x[0] if isinstance(x, list) else x


def cover_url(book):
    for key in ("image", "cached_image"):
        val = book.get(key)
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                return val or None
        if isinstance(val, dict) and val.get("url"):
            return val["url"]
    return None


def fetch_month(token, year, month, debug=False):
    me = gql(token, ME_QUERY)
    if me.get("errors"):
        sys.exit(f"Could not identify you: {json.dumps(me['errors'], indent=2)}")
    me = first(me["data"]["me"])
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    variables = {"uid": me["id"], "start": start.isoformat(), "end": end.isoformat()}

    last_errors = None
    for image_field in IMAGE_FIELDS:
        resp = gql(token, BOOKS_QUERY.replace("%IMAGE%", image_field), variables)
        if resp.get("errors"):
            last_errors = resp["errors"]
            continue
        rows = resp["data"]["user_books"]
        if debug:
            print(json.dumps(rows, indent=2))
        books = []
        for r in rows:
            reads = r.get("user_book_reads") or [{}]
            book = r["book"]
            authors = []
            for c in book.get("contributions") or []:
                name = (c.get("author") or {}).get("name")
                if name and name not in authors:
                    authors.append(name)
            books.append({
                "title": book.get("title") or "Untitled",
                "authors": authors,
                "url": cover_url(book),
                "finished": reads[0].get("finished_at") or "",
                "started": reads[0].get("started_at") or "",
            })
        books.sort(key=lambda b: b["finished"])
        return books, me.get("username")
    sys.exit(f"The books query failed:\n{json.dumps(last_errors, indent=2)}")


def download(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hc-wrapup-script/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGB")
    except Exception as e:  # noqa: BLE001 - any failure just means "use a placeholder"
        print(f"  (could not load cover {url}: {e})", file=sys.stderr)
        return None


# ------------------------------------------------------------ Drawing ----

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",   # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    "C:/Windows/Fonts/arialbd.ttf",                          # Windows
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def placeholder(book, width):
    height = int(width * 1.5)
    img = Image.new("RGB", (width, height), (168, 213, 216))
    d = ImageDraw.Draw(img)
    f_title, f_auth = load_font(22), load_font(18)
    y, pad = 20, 18
    for line in wrap(d, book["title"], f_title, width - 2 * pad):
        d.text((pad, y), line, font=f_title, fill=(35, 35, 45))
        y += 28
    if book["authors"]:
        y += 10
        for line in wrap(d, ", ".join(book["authors"]), f_auth, width - 2 * pad):
            d.text((pad, y), line, font=f_auth, fill=(70, 80, 90))
            y += 23
    return img


def render(books, title, out_path, columns=4, cover_w=300):
    """books: list of dicts with 'image' (PIL.Image or None), 'title', 'authors'."""
    gap, margin, header_h = 18, 40, 120
    tiles = []
    for b in books:
        img = b.get("image")
        if img is None:
            img = placeholder(b, cover_w)
        else:
            h = min(int(img.height * cover_w / img.width), cover_w * 2)
            img = img.resize((cover_w, h), Image.LANCZOS)
        tiles.append(img)

    columns = max(1, min(columns, len(tiles) or 1))
    heights = [0] * columns
    placed = []  # (x, y, img)
    for img in tiles:  # masonry: drop each cover into the shortest column
        c = heights.index(min(heights))
        placed.append((margin + c * (cover_w + gap), header_h + margin // 2 + heights[c], img))
        heights[c] += img.height + gap

    width = 2 * margin + columns * cover_w + (columns - 1) * gap
    height = header_h + margin // 2 + max(heights or [0]) + margin
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))

    # soft drop shadows, blurred once for all tiles
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x, y, img in placed:
        sd.rectangle([x + 3, y + 6, x + img.width + 3, y + img.height + 6], fill=(0, 0, 0, 70))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
    for x, y, img in placed:
        canvas.paste(img, (x, y))

    # header bar
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([margin // 2, 22, width - margin // 2, header_h - 8],
                        radius=18, fill=(224, 250, 255))
    f = load_font(46)
    tw = d.textlength(title, font=f)
    d.text(((width - tw) / 2, 22 + (header_h - 30 - 46) / 2 - 4), title,
           font=f, fill=(30, 30, 40))

    canvas.convert("RGB").save(out_path)


# ------------------------------------------- Themed layouts (all drawn in code) ----
# Wood grain, cork speckle, shadows and pins are generated procedurally with
# Pillow. The only photographic content in the output is the book covers.
import math  # noqa: E402
import random  # noqa: E402


def clamp_color(base, shade):
    return tuple(max(0, min(255, c + shade)) for c in base)


def wood_texture(size, base, rng, strength=14):
    w, h = size
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 2):  # long horizontal grain streaks
        x = rng.randint(-w // 3, w // 2)
        d.line([(x, y), (x + rng.randint(w // 3, w), y)],
               fill=clamp_color(base, rng.randint(-strength, strength)),
               width=rng.choice([1, 1, 2]))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def cork_texture(size, rng):
    w, h = size
    base = (196, 154, 108)
    img = Image.new("RGB", size, base)
    d = ImageDraw.Draw(img)
    for _ in range(w * h // 45):  # random speckles in slightly different browns
        x, y, r = rng.randrange(w), rng.randrange(h), rng.choice([1, 1, 2, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill=clamp_color(base, rng.randint(-38, 30)))
    return img.filter(ImageFilter.GaussianBlur(0.7))


def paste_shadowed(canvas, img, xy, blur=8, offset=(6, 9), opacity=120):
    """Paste an RGBA image onto an RGBA canvas with a soft drop shadow."""
    pad = blur * 3
    layer = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    alpha = img.getchannel("A").point(lambda a: a * opacity // 255)
    layer.paste((0, 0, 0, 255), (pad, pad), alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.paste(layer, (xy[0] + offset[0] - pad, xy[1] + offset[1] - pad), layer)
    canvas.paste(img, xy, img)


def tile_for(book, height):
    img = book.get("image")
    if img is None:
        img = placeholder(book, int(height / 1.5))
    else:
        img = img.resize((max(1, int(img.width * height / img.height)), height), Image.LANCZOS)
    return img.convert("RGBA")


def split_rows(items, per_row):
    """Split into the fewest rows, as evenly as possible (8 books, 4 per row -> 4+4)."""
    rows = max(1, math.ceil(len(items) / per_row))
    size = math.ceil(len(items) / rows)
    return [items[i:i + size] for i in range(0, len(items), size)]


def text_plaque(text, base, text_color, font_size, rng, pad=(46, 18)):
    f = load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(probe.textlength(text, font=f))
    w, h = tw + 2 * pad[0], font_size + 2 * pad[1]
    img = wood_texture((w, h), base, rng, 10) if base[0] < 200 else Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=clamp_color(base, -45), width=3)
    d.text((pad[0], pad[1] - 4), text, font=f, fill=text_color)
    return img.convert("RGBA")


def render_shelf(books, title, out_path, per_row=4, seed=0):
    rng = random.Random(seed)
    H, gap, frame, board, headroom, margin, head = 420, 16, 34, 28, 40, 50, 150
    rows = split_rows([tile_for(b, H) for b in books], per_row)
    row_w = [sum(t.width for t in r) + gap * (len(r) - 1) for r in rows]
    unit_w = max(row_w) + 80 + 2 * frame
    cell_h = headroom + H + board
    unit_h = frame + len(rows) * cell_h
    W, Hc = unit_w + 2 * margin, head + unit_h + margin
    ux, uy = margin, head

    canvas = Image.new("RGBA", (W, Hc))
    d = ImageDraw.Draw(canvas)
    for y in range(Hc):  # soft wall gradient
        t = y / Hc
        d.line([(0, y), (W, y)], fill=(int(214 - 24 * t), int(224 - 20 * t), int(226 - 18 * t), 255))

    # shelf unit: dark back panel, lighter frame and boards
    unit = Image.new("RGB", (unit_w, unit_h))
    unit.paste(wood_texture((unit_w, unit_h), (96, 68, 48), rng), (0, 0))
    light = (156, 108, 68)
    unit.paste(wood_texture((unit_w, frame), light, rng), (0, 0))
    unit.paste(wood_texture((frame, unit_h), light, rng), (0, 0))
    unit.paste(wood_texture((frame, unit_h), light, rng), (unit_w - frame, 0))
    ud = ImageDraw.Draw(unit, "RGBA")
    for i in range(len(rows)):
        by = frame + (i + 1) * cell_h - board
        ud.rectangle([frame, by - 14, unit_w - frame, by], fill=(0, 0, 0, 38))  # shade above board
        unit.paste(wood_texture((unit_w, board), light, rng), (0, by))
        ud.line([(0, by), (unit_w, by)], fill=(255, 235, 200, 90), width=2)    # lit top edge
        ud.rectangle([frame, by + board, unit_w - frame, by + board + 10], fill=(0, 0, 0, 55))
    paste_shadowed(canvas, unit.convert("RGBA"), (ux, uy), blur=14, offset=(0, 12), opacity=90)

    for i, (row, rw) in enumerate(zip(rows, row_w)):
        board_top = uy + frame + (i + 1) * cell_h - board
        x = ux + (unit_w - rw) // 2
        for t in row:
            tilt = rng.choice([0, 0, 0, 0, -3, 2, 3])
            r = t.rotate(tilt, expand=True, resample=Image.BICUBIC)
            paste_shadowed(canvas, r, (x + (t.width - r.width) // 2, board_top - r.height),
                           blur=7, offset=(5, 0), opacity=150)
            x += t.width + gap

    plaque = text_plaque(title, (120, 84, 52), (248, 236, 210), 44, rng)
    paste_shadowed(canvas, plaque, ((W - plaque.width) // 2, 40), blur=6, offset=(0, 6), opacity=110)
    canvas.convert("RGB").save(out_path)


def draw_pin(canvas, px, py, col):
    ov = Image.new("RGBA", (70, 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.ellipse([27, 33, 51, 57], fill=(0, 0, 0, 80))  # shadow
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(ov)
    d.ellipse([23, 23, 47, 47], fill=col + (255,), outline=clamp_color(col, -60) + (255,), width=2)
    d.ellipse([28, 27, 34, 33], fill=(255, 255, 255, 200))  # highlight
    canvas.paste(ov, (int(px) - 35, int(py) - 35), ov)


def render_cork(books, title, out_path, per_row=4, seed=0):
    rng = random.Random(seed)
    H, frame, head = 400, 36, 150
    rows = split_rows([tile_for(b, H) for b in books], per_row)
    cols = max(len(r) for r in rows)
    cell_w = max(t.width for r in rows for t in r) + 60
    cell_h = H + 70
    inner_w, inner_h = cols * cell_w + 60, head + len(rows) * cell_h + 30
    W, Hc = inner_w + 2 * frame, inner_h + 2 * frame

    canvas = wood_texture((W, Hc), (140, 98, 62), rng).convert("RGBA")
    canvas.paste(cork_texture((inner_w, inner_h), rng), (frame, frame))
    ImageDraw.Draw(canvas).rectangle([frame - 2, frame - 2, W - frame + 1, Hc - frame + 1],
                                     outline=(84, 56, 32, 255), width=4)

    # paper note for the title
    note = text_plaque(title, (251, 245, 226), (45, 38, 30), 42, rng)
    note = note.rotate(-1.5, expand=True, resample=Image.BICUBIC)
    paste_shadowed(canvas, note, ((W - note.width) // 2, frame + 30), blur=6, offset=(4, 7), opacity=120)

    pins = [(200, 45, 45), (45, 95, 195), (232, 182, 35), (45, 150, 85)]
    for ri, row in enumerate(rows):
        x_off = (cols - len(row)) * cell_w / 2
        for ci, t in enumerate(row):
            cx = frame + 30 + x_off + ci * cell_w + cell_w / 2 + rng.randint(-12, 12)
            cy = frame + head + ri * cell_h + cell_h / 2 + rng.randint(-10, 10)
            angle = rng.uniform(-6, 6)
            r = t.rotate(angle, expand=True, resample=Image.BICUBIC)
            paste_shadowed(canvas, r, (int(cx - r.width / 2), int(cy - r.height / 2)),
                           blur=7, offset=(5, 9), opacity=125)
            # pin near the top centre of the (rotated) cover
            a, v = math.radians(angle), -t.height / 2 + 22
            px, py = cx + v * math.sin(a), cy + v * math.cos(a)
            col = pins[(ri * 3 + ci) % len(pins)]
            draw_pin(canvas, px, py, col)
    canvas.convert("RGB").save(out_path)


# ------------------------------------- More layouts: calendar, rainbow, eight ----
import colorsys  # noqa: E402


def dominant_color(book):
    """Average colour of a cover, weighted toward saturated/bright pixels."""
    img = book.get("image")
    if img is None:
        return (168, 213, 216)  # the placeholder tile colour
    small = img.convert("RGB").resize((20, 30))
    px = small.load()
    tr = tg = tb = tw = 0.0
    for x in range(small.width):
        for y in range(small.height):
            r, g, b = px[x, y]
            _, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            wgt = sat * val + 0.001
            tr, tg, tb, tw = tr + r * wgt, tg + g * wgt, tb + b * wgt, tw + wgt
    return (int(tr / tw), int(tg / tw), int(tb / tw))


def rainbow_key(color):
    h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in color))
    if sat < 0.2 or val < 0.15:      # black / grey / white covers go last, dark -> light
        return (1, val)
    return (0, (h + 0.06) % 1.0)     # shifted so pinkish-reds sort with the reds


def centered_text(canvas, text, y, size, fill):
    d = ImageDraw.Draw(canvas)
    f = load_font(size)
    while size > 20 and d.textlength(text, font=f) > canvas.width - 60:
        size -= 2
        f = load_font(size)
    d.text(((canvas.width - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


def render_rainbow(books, title, out_path, per_row=None):
    H, gap, margin, head, strip_h = 400, 22, 50, 140, 46
    pairs = sorted(((tile_for(b, H), dominant_color(b)) for b in books),
                   key=lambda p: rainbow_key(p[1]))
    rows = split_rows(pairs, per_row or (len(pairs) if len(pairs) <= 5 else 4))
    cols = max(len(r) for r in rows)
    cw = max(t.width for t, _ in pairs)
    row_h = H + 14 + strip_h + 36
    W = 2 * margin + cols * cw + (cols - 1) * gap
    Hc = head + len(rows) * row_h + margin - 10

    # background: the sorted cover colours as a soft gradient that runs left-to-right
    # along each row, continuing on the next row (the same order you read the covers)
    colors = [c for _, c in pairs]
    canvas = Image.new("RGBA", (W, Hc))
    d = ImageDraw.Draw(canvas)
    tops = [0] + [head + ri * row_h - 18 for ri in range(1, len(rows))] + [Hc]
    for ri in range(len(rows)):
        for x in range(W):
            t = (ri + x / max(1, W - 1)) / len(rows) * (len(colors) - 1)
            i = min(int(t), len(colors) - 2) if len(colors) > 1 else 0
            f = t - i
            c1, c2 = colors[i], colors[min(i + 1, len(colors) - 1)]
            mixed = [c1[k] + (c2[k] - c1[k]) * f for k in range(3)]
            d.line([(x, tops[ri]), (x, tops[ri + 1])],
                   fill=tuple(int(m * 0.28 + 255 * 0.72) for m in mixed) + (255,))

    pill = Image.new("RGBA", (W - 2 * margin, 86), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle([0, 0, pill.width - 1, pill.height - 1],
                                           radius=22, fill=(255, 255, 255, 190))
    canvas.alpha_composite(pill, (margin, 28))
    centered_text(canvas, title, 28 + 12, 46, (30, 30, 40))

    for ri, row in enumerate(rows):
        x_off = (cols - len(row)) * (cw + gap) / 2
        y0 = head + ri * row_h
        for ci, (t, col) in enumerate(row):
            x = int(margin + x_off + ci * (cw + gap))
            paste_shadowed(canvas, t, (x + (cw - t.width) // 2, y0 + (H - t.height)), blur=7)
            sw = ImageDraw.Draw(canvas)
            sw.rounded_rectangle([x, y0 + H + 14, x + cw, y0 + H + 14 + strip_h],
                                 radius=10, fill=col + (255,), outline=(255, 255, 255, 255), width=3)
    canvas.convert("RGB").save(out_path)


BOOK_COLORS = [(231, 76, 60), (52, 152, 219), (46, 174, 96), (155, 89, 182),
               (240, 165, 20), (26, 188, 156), (233, 30, 120), (90, 100, 220)]


def parse_ymd(text):
    try:
        return date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


def render_calendar(books, title, out_path, year, month):
    """Cover on the day you started, a coloured arrow running to the day you finished."""
    cw, margin, head, label_h, lane_h = 190, 40, 150, 40, 22
    month_start = date(year, month, 1)
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)  # weeks start Sunday
    pos = {day: (wi, di) for wi, wk in enumerate(weeks) for di, day in enumerate(wk) if day}

    # work out start/finish days, colours and arrow lanes for every book
    infos = []
    for b in books:
        fin = parse_ymd(b.get("finished"))
        if fin is None or fin.month != month or fin.year != year:
            continue
        st = parse_ymd(b.get("started"))
        tail = bool(st and st < month_start)          # started in an earlier month
        sday = 1 if tail else (st.day if st and st <= fin else fin.day)
        infos.append({"book": b, "fday": fin.day, "sday": sday, "tail": tail,
                      "from_label": f"from {calendar.month_abbr[st.month]} {st.day}" if tail else "",
                      "cover_day": fin.day if tail else sday})
    infos.sort(key=lambda i: (i["sday"], i["fday"]))
    lane_ends = []
    for n, info in enumerate(infos):
        info["color"] = BOOK_COLORS[n % len(BOOK_COLORS)]
        info["bar"] = info["sday"] < info["fday"]
        if info["bar"]:
            for li, end_day in enumerate(lane_ends):
                if end_day < info["sday"]:
                    info["lane"], lane_ends[li] = li, info["fday"]
                    break
            else:
                info["lane"] = len(lane_ends)
                lane_ends.append(info["fday"])
    lanes = len(lane_ends)

    cover_h = 230
    ch = 32 + cover_h + 14 + lane_h * lanes
    W, Hc = 2 * margin + 7 * cw, head + label_h + len(weeks) * ch + margin
    canvas = Image.new("RGBA", (W, Hc), (250, 247, 241, 255))
    centered_text(canvas, title, 40, 56, (35, 32, 30))
    d = ImageDraw.Draw(canvas)
    f_lab, f_day, f_small = load_font(20), load_font(18), load_font(12)
    for i, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
        tw = d.textlength(name, font=f_lab)
        d.text((margin + i * cw + (cw - tw) / 2, head + 8), name, font=f_lab, fill=(120, 112, 104))

    def cell_xy(day):
        wi, di = pos[day]
        return margin + di * cw, head + label_h + wi * ch

    for wi, week in enumerate(weeks):
        for di, day in enumerate(week):
            x0, y0 = margin + di * cw, head + label_h + wi * ch
            d.rectangle([x0, y0, x0 + cw, y0 + ch],
                        fill=(255, 255, 255, 255) if day else (241, 237, 229, 255),
                        outline=(224, 218, 206, 255), width=2)
            if day:
                d.text((x0 + 9, y0 + 6), str(day), font=f_day, fill=(150, 142, 132))

    # covers, shown on the day you started (or on the finish day if there's no earlier start)
    by_day = {}
    for info in infos:
        by_day.setdefault(info["cover_day"], []).append(info)
    for day, todays in by_day.items():
        x0, y0 = cell_xy(day)
        avail_w = cw - 18
        for k, info in enumerate(todays):
            n = len(todays)
            t = tile_for(info["book"], cover_h if n == 1 else int(cover_h * 0.74))
            if t.width > avail_w * (1 if n == 1 else 0.7):
                nw = int(avail_w * (1 if n == 1 else 0.7))
                t = t.resize((nw, int(t.height * nw / t.width)), Image.LANCZOS)
            framed = Image.new("RGBA", (t.width + 8, t.height + 8), info["color"] + (255,))
            framed.paste(t, (4, 4))
            if n == 1:
                px, py = x0 + (cw - framed.width) // 2, y0 + 30
            else:  # several books on the same day: cascade them
                px = x0 + 9 + int(k * (avail_w - framed.width) / (n - 1))
                py = y0 + 30 + int(k * (cover_h - framed.height) / (n - 1))
            paste_shadowed(canvas, framed, (px, py), blur=4, offset=(3, 4), opacity=110)

    # arrows from start day to finish day, one lane per overlapping book
    d = ImageDraw.Draw(canvas)
    for info in infos:
        color = info["color"]
        if info["bar"]:
            days = range(info["sday"], info["fday"] + 1)
            for wi in sorted({pos[x][0] for x in days}):
                ds = [x for x in days if pos[x][0] == wi]
                d1, d2 = ds[0], ds[-1]
                row_y = head + label_h + wi * ch
                yc = row_y + 32 + cover_h + 14 + info["lane"] * lane_h + lane_h // 2
                starts_here = d1 == info["sday"] and not info["tail"]
                ends_here = d2 == info["fday"]
                x1 = margin + pos[d1][1] * cw + (cw // 2 if starts_here else 0)
                x2 = margin + (pos[d2][1] + 1) * cw - (cw // 2 if ends_here else 0)
                d.rounded_rectangle([x1, yc - 5, x2 - (8 if ends_here else 0), yc + 5],
                                    radius=5, fill=color + (255,))
                if starts_here:
                    d.ellipse([x1 - 8, yc - 8, x1 + 8, yc + 8], fill=color + (255,),
                              outline=(255, 255, 255, 255), width=2)
                if ends_here:  # arrowhead pointing at the finish day
                    d.polygon([(x2 - 14, yc - 12), (x2 + 8, yc), (x2 - 14, yc + 12)],
                              fill=color + (255,))
                if info["tail"] and d1 == info["sday"] and x2 - x1 > 110:
                    d.text((x1 + 10, yc - 7), info["from_label"], font=f_small, fill=(255, 255, 255, 255))
        # check-mark badge in the corner of the finish day
        fx, fy = cell_xy(info["fday"])
        same = [i for i in infos if i["fday"] == info["fday"]]
        bx = fx + cw - 18 - same.index(info) * 24
        by = fy + 17
        d.ellipse([bx - 10, by - 10, bx + 10, by + 10], fill=color + (255,))
        d.line([(bx - 5, by), (bx - 1, by + 4), (bx + 5, by - 4)], fill=(255, 255, 255, 255), width=3)
    canvas.convert("RGB").save(out_path)


def render_eight(books, title, out_path, seed=0):
    """Covers arranged around two stacked rings that form a figure 8."""
    rng = random.Random(seed)
    h, margin, head, band = 240, 60, 150, 40
    tiles = [tile_for(b, h) for b in books]
    cw = max(t.width for t in tiles)
    top_n = math.ceil(len(tiles) / 2)
    groups = [tiles[:top_n], tiles[top_n:]]
    # tight rings: the covers at the waist overlap a little, like a woven 8
    R = max(1.35 * h, max(len(g) for g in groups) * (cw + 18) / (2 * math.pi))
    W = int(2 * R + band + 2 * margin)
    cx, cy1 = W / 2, head + R + 40
    centers = [cy1, cy1 + 2 * R]
    Hc = int(centers[1] + R + band / 2 + margin)

    canvas = Image.new("RGBA", (W, Hc), (251, 247, 240, 255))
    centered_text(canvas, title, 40, 52, (35, 32, 30))
    d = ImageDraw.Draw(canvas)
    for cy in centers:  # thick band so the "8" reads as a shape behind the covers
        d.ellipse([cx - R - band / 2, cy - R - band / 2, cx + R + band / 2, cy + R + band / 2],
                  outline=(236, 227, 211, 255), width=band)

    for gi, (group, cy) in enumerate(zip(groups, centers)):
        m = len(group)
        base = 180 if gi == 0 else 0  # leave a gap where the two rings touch
        angles = [(base + (k + 0.5) * 360 / m) % 360 for k in range(m)]
        order = sorted(range(m), key=lambda k: (angles[k] - 270) % 360)  # clockwise from the left
        for t, k in zip(group, order):
            th = math.radians(angles[k])
            x, y = cx + R * math.sin(th), cy - R * math.cos(th)
            r = t.rotate(rng.uniform(-5, 5), expand=True, resample=Image.BICUBIC)
            paste_shadowed(canvas, r, (int(x - r.width / 2), int(y - r.height / 2)), blur=7)
    canvas.convert("RGB").save(out_path)


# --------------------------------------------------------------- Main ----

def parse_month(text):
    if text.isdigit():
        m = int(text)
    else:
        names = {n.lower(): i for i, n in enumerate(calendar.month_name) if n}
        names.update({n.lower(): i for i, n in enumerate(calendar.month_abbr) if n})
        m = names.get(text.lower(), 0)
    if not 1 <= m <= 12:
        sys.exit(f"Don't understand month {text!r} (use 1-12 or a name like 'august').")
    return m


def main():
    p = argparse.ArgumentParser(description="Monthly cover-collage wrap-up from Hardcover.")
    p.add_argument("month", help="1-12 or a month name")
    p.add_argument("year", type=int)
    p.add_argument("--style", choices=["grid", "shelf", "cork", "calendar", "rainbow", "eight"],
                   default="grid",
                   help="grid (default), shelf, cork, calendar (by finish date), "
                        "rainbow (sorted by cover colour) or eight (figure-8 ring layout)")
    p.add_argument("--columns", type=int, default=None,
                   help="books per row for grid/shelf/cork/rainbow (default 4)")
    p.add_argument("--seed", type=int, default=0,
                   help="changes the random tilt/placement for shelf and cork")
    p.add_argument("--name", help="prefix for the title, e.g. \"Sam's\"")
    p.add_argument("-o", "--output", help="output PNG path")
    p.add_argument("--debug", action="store_true", help="print the raw API response")
    args = p.parse_args()

    token = os.environ.get("HARDCOVER_TOKEN")
    if not token:
        sys.exit("Set the HARDCOVER_TOKEN environment variable first.")

    month = parse_month(args.month)
    books, _username = fetch_month(token, args.year, month, args.debug)
    if not books:
        sys.exit(f"No finished reads found for {calendar.month_name[month]} {args.year}.")

    print(f"Found {len(books)} book(s); downloading covers...")
    for b in books:
        b["image"] = download(b["url"]) if b["url"] else None

    title = f"{calendar.month_name[month]} {args.year} Reads"
    if args.name:
        title = f"{args.name} {title}"
    out = args.output or f"wrapup-{args.year}-{month:02d}-{args.style}.png"
    cols = args.columns or 4
    if args.style == "shelf":
        render_shelf(books, title, out, per_row=cols, seed=args.seed)
    elif args.style == "cork":
        render_cork(books, title, out, per_row=cols, seed=args.seed)
    elif args.style == "calendar":
        render_calendar(books, title, out, args.year, month)
    elif args.style == "rainbow":
        render_rainbow(books, title, out, per_row=args.columns)
    elif args.style == "eight":
        render_eight(books, title, out, seed=args.seed)
    else:
        render(books, title, out, columns=cols)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
