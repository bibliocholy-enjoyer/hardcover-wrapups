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
