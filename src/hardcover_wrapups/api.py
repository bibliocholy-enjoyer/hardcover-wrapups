"""Hardcover GraphQL queries: who the user is, and which books they finished in a month."""
import json
import sys
import urllib.error
import urllib.request
from datetime import date

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
    """Fetch a cover image's bytes, or None on any failure (a placeholder is drawn instead)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hc-wrapup-script/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001 - any failure just means "use a placeholder"
        print(f"  (could not load cover {url}: {e})", file=sys.stderr)
        return None
