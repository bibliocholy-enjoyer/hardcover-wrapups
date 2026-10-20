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
    uv run hc-wrapup 8 2026 --debug           # print what the API returned
"""
import argparse
import calendar
import os
import sys

from . import api, render


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
    p.add_argument("--style", choices=render.STYLES, default="grid",
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
    books, _username = api.fetch_month(token, args.year, month, args.debug)
    if not books:
        sys.exit(f"No finished reads found for {calendar.month_name[month]} {args.year}.")

    print(f"Found {len(books)} book(s); downloading covers...")
    for b in books:
        b["image"] = render.open_cover(api.download(b["url"])) if b["url"] else None

    title = f"{calendar.month_name[month]} {args.year} Reads"
    if args.name:
        title = f"{args.name} {title}"
    out = args.output or f"wrapup-{args.year}-{month:02d}-{args.style}.png"
    render.render_style(args.style, books, title, out, args.year, month,
                        columns=args.columns, seed=args.seed)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
