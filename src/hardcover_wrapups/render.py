"""Cover-collage renderers. Each one takes a list of book dicts and writes a PNG.

Book dicts have 'title', 'authors', 'finished', 'started' (from api.fetch_month) and
'image' (a PIL.Image, or None to draw a placeholder tile).
"""
import calendar
import functools
import io
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

STYLES = ["grid", "seasonal", "shelf", "cork", "calendar"]
DEFAULT_STYLE = "grid"
MAX_COLUMNS = 8
MAX_NAME_LENGTH = 40

# Covers are never drawn larger than about 300x600, so shrink them on load to save memory.
COVER_MAX_SIZE = (800, 1000)


def open_cover(data):
    """Decode downloaded cover bytes, or return None so a placeholder is drawn."""
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", COVER_MAX_SIZE)  # lets JPEGs decode at reduced size
        img = img.convert("RGB")
        img.thumbnail(COVER_MAX_SIZE, Image.LANCZOS)
        return img
    except Exception:  # noqa: BLE001 - an undecodable cover just gets a placeholder
        return None


def make_title(year, month, name=None):
    """'August 2026 Reads', or "Sam's August 2026 Reads" with a (trimmed) name."""
    title = f"{calendar.month_name[month]} {year} Reads"
    name = " ".join((name or "").split())[:MAX_NAME_LENGTH]
    return f"{name} {title}" if name else title


# ------------------------------------------------------------ Drawing ----

# Bundled so images look the same on every machine; see fonts/DejaVu-LICENSE.
FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf"


@functools.cache
def load_font(size):
    return ImageFont.truetype(FONT_PATH, size)


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


def grid_tiles(books, cover_w):
    """Covers scaled to cover_w wide (at most twice as tall), or placeholder tiles."""
    tiles = []
    for b in books:
        img = b.get("image")
        if img is None:
            img = placeholder(b, cover_w)
        else:
            h = min(int(img.height * cover_w / img.width), cover_w * 2)
            img = img.resize((cover_w, h), Image.LANCZOS)
        tiles.append(img)
    return tiles


def grid_layout(tiles, columns, cover_w, gap, left, top):
    """Place tiles in rows with their tops lined up, centring a short last row.

    Returns ([(x, y, tile), ...], the grid's width, and the y just below the last row).
    """
    columns = max(1, min(columns, len(tiles) or 1))
    grid_w = columns * cover_w + (columns - 1) * gap
    placed = []
    y = top
    for start in range(0, len(tiles), columns):
        row = tiles[start:start + columns]
        x = left + (columns - len(row)) * (cover_w + gap) // 2
        for img in row:
            placed.append((x, y, img))
            x += cover_w + gap
        y += max(img.height for img in row) + gap
    return placed, grid_w, y - gap


def paste_tiles(canvas, placed, opacity=70, blur=7):
    """Paste tiles onto an RGBA canvas over soft drop shadows (blurred once for all)."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x, y, img in placed:
        sd.rectangle([x + 3, y + 6, x + img.width + 3, y + img.height + 6], fill=(0, 0, 0, opacity))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    for x, y, img in placed:
        canvas.paste(img, (x, y))


def render(books, title, out_path, columns=4, cover_w=300):
    """books: list of dicts with 'image' (PIL.Image or None), 'title', 'authors'."""
    gap, margin, header_h = 18, 40, 120
    tiles = grid_tiles(books, cover_w)
    placed, grid_w, bottom = grid_layout(tiles, columns, cover_w, gap, margin, header_h + margin // 2)
    width, height = 2 * margin + grid_w, bottom + margin
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    paste_tiles(canvas, placed)

    # header bar
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([margin // 2, 22, width - margin // 2, header_h - 8],
                        radius=18, fill=(224, 250, 255))
    f = load_font(46)
    tw = d.textlength(title, font=f)
    d.text(((width - tw) / 2, 22 + (header_h - 30 - 46) / 2 - 4), title,
           font=f, fill=(30, 30, 40))

    canvas.convert("RGB").save(out_path, format="PNG")


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
    canvas.convert("RGB").save(out_path, format="PNG")


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
    canvas.convert("RGB").save(out_path, format="PNG")


# ---------------------------------------------------------- Calendar ----


def centered_text(canvas, text, y, size, fill):
    d = ImageDraw.Draw(canvas)
    f = load_font(size)
    while size > 20 and d.textlength(text, font=f) > canvas.width - 60:
        size -= 2
        f = load_font(size)
    d.text(((canvas.width - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


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
    canvas.convert("RGB").save(out_path, format="PNG")


def render_style(style, books, title, out, year, month, columns=None, seed=0, theme=None):
    """Render `books` in the named style to `out` (a path or a writable binary file).

    `theme` picks the seasonal style's season; None means the month's season.
    """
    if columns is not None:
        columns = max(1, min(columns, MAX_COLUMNS))
    cols = columns or 4
    if style == "shelf":
        render_shelf(books, title, out, per_row=cols, seed=seed)
    elif style == "cork":
        render_cork(books, title, out, per_row=cols, seed=seed)
    elif style == "calendar":
        render_calendar(books, title, out, year, month)
    elif style == "seasonal":
        from . import seasonal  # imports this module, so load it on demand

        theme = theme or seasonal.theme_for_month(month)
        seasonal.render_seasonal(books, title, out, columns=cols, theme=theme, seed=seed)
    elif style == "grid":
        render(books, title, out, columns=cols)
    else:
        raise ValueError(f"Unknown style {style!r}")
