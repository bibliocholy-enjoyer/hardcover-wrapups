import io

import pytest
from PIL import Image

from hardcover_wrapups import render

BOOKS = [
    {"title": "A Book With a Fairly Long Title", "authors": ["Some Author"],
     "started": "2026-08-01", "finished": "2026-08-03", "image": None},
    {"title": "Second", "authors": [], "started": "2026-07-20", "finished": "2026-08-15",
     "image": Image.new("RGB", (200, 300), (200, 40, 40))},
    {"title": "Third", "authors": ["A", "B"], "started": "", "finished": "2026-08-31",
     "image": Image.new("RGB", (180, 280), (40, 90, 200))},
]


@pytest.mark.parametrize("style", render.STYLES)
def test_every_style_renders_a_png(style):
    out = io.BytesIO()
    render.render_style(style, [dict(b) for b in BOOKS], "August 2026 Reads", out, 2026, 8)
    img = Image.open(io.BytesIO(out.getvalue()))
    assert img.format == "PNG"
    assert img.width > 0 and img.height > 0


def test_open_cover_handles_bad_data():
    assert render.open_cover(None) is None
    assert render.open_cover(b"not an image") is None


def test_open_cover_shrinks_large_images():
    buf = io.BytesIO()
    Image.new("RGB", (3000, 4500), (10, 20, 30)).save(buf, format="JPEG")
    img = render.open_cover(buf.getvalue())
    assert img.width <= render.COVER_MAX_SIZE[0] and img.height <= render.COVER_MAX_SIZE[1]
    assert img.mode == "RGB"


def test_make_title_trims_name():
    assert render.make_title(2026, 8) == "August 2026 Reads"
    assert render.make_title(2026, 8, "  Sam's  ") == "Sam's August 2026 Reads"
    long = render.make_title(2026, 8, "x" * 500)
    assert long == "x" * render.MAX_NAME_LENGTH + " August 2026 Reads"


def test_columns_are_clamped():
    books = [dict(BOOKS[0]) for _ in range(12)]
    out = io.BytesIO()
    render.render_style("grid", books, "T", out, 2026, 8, columns=10_000)
    # grid width is 2 * margin + columns * cover + (columns - 1) * gap
    assert Image.open(io.BytesIO(out.getvalue())).width == 80 + render.MAX_COLUMNS * 300 + 7 * 18


def test_uses_bundled_font():
    assert str(render.load_font(20).path) == str(render.FONT_PATH)
