"""Make a StoryGraph-style monthly wrap-up cover collage from your Hardcover library.

Setup:
    export HARDCOVER_TOKEN="hc_pat_..."

Usage:
    uv run hc-wrapup 8 2026
    uv run hc-wrapup august 2026 --columns 5 --name "Sam's"
    uv run hc-wrapup 8 2026 --style shelf     # bookshelf
    uv run hc-wrapup 8 2026 --style cork      # corkboard
    uv run hc-wrapup 8 2026 --style calendar  # covers on the day you finished them
    uv run hc-wrapup 8 2026 --style rainbow   # sorted by cover colour
    uv run hc-wrapup 8 2026 --style eight     # covers arranged in a figure 8
    uv run hc-wrapup 8 2026 --privacy public  # leave out followers-only and private books
    uv run hc-wrapup 8 2026 --debug           # print what the API returned
"""
import argparse
import asyncio
import calendar
import logging
import os
import sys

from . import api, render

PRIVACY_LEVELS = {"public": api.PUBLIC, "followers": api.FOLLOWERS_ONLY, "private": api.PRIVATE}


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
    p.add_argument("--style", choices=render.STYLES, default=render.DEFAULT_STYLE,
                   help="grid (default), shelf, cork, calendar (by finish date), "
                        "rainbow (sorted by cover colour) or eight (figure-8 ring layout)")
    p.add_argument("--columns", type=int, default=None,
                   help=f"books per row for grid/shelf/cork/rainbow (default 4, max {render.MAX_COLUMNS})")
    p.add_argument("--seed", type=int, default=0,
                   help="changes the random tilt/placement for shelf and cork")
    p.add_argument("--name", help="prefix for the title, e.g. \"Sam's\"")
    p.add_argument("--privacy", choices=PRIVACY_LEVELS, default="private",
                   help="most private library entries to include: public, followers "
                        "or private (default: private, i.e. everything)")
    p.add_argument("-o", "--output", help="output PNG path")
    p.add_argument("--debug", action="store_true", help="print the raw API response")
    args = p.parse_args()
    logging.basicConfig(format="  (%(message)s)", level=logging.WARNING)

    token = os.environ.get("HARDCOVER_TOKEN")
    if not token:
        sys.exit("Set the HARDCOVER_TOKEN environment variable first.")

    month = parse_month(args.month)
    try:
        books = asyncio.run(fetch_books(token, args.year, month,
                                        PRIVACY_LEVELS[args.privacy], args.debug))
    except api.HardcoverError as e:
        sys.exit(str(e))
    if not books:
        sys.exit(f"No finished reads found for {calendar.month_name[month]} {args.year}.")

    title = render.make_title(args.year, month, args.name)
    out = args.output or f"wrapup-{args.year}-{month:02d}-{args.style}.png"
    render.render_style(args.style, books, title, out, args.year, month,
                        columns=args.columns, seed=args.seed)
    print(f"Saved {out}")


async def fetch_books(token, year, month, max_privacy, debug):
    async with api.new_client() as client:
        books, _username = await api.fetch_month(client, token, year, month, max_privacy, debug)
        if books:
            print(f"Found {len(books)} book(s); downloading covers...")
        covers = await api.download_covers(client, [b["url"] for b in books])
    for b, data in zip(books, covers):
        b["image"] = render.open_cover(data)
    return books


if __name__ == "__main__":
    main()
