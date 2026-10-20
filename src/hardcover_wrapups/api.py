"""Hardcover GraphQL queries: who the user is, and which books they finished in a month."""
import asyncio
import json
import logging
from datetime import date
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.hardcover.app/v1/graphql"
USER_AGENT = "hardcover-wrapups/0.1 (+https://github.com/bibliocholy-enjoyer/hardcover-wrapups)"

# Hardcover's privacy_settings table: each library entry has one of these.
PUBLIC, FOLLOWERS_ONLY, PRIVATE = 1, 2, 3

# Ways Hardcover might expose the cover image; we try each until one is accepted.
IMAGE_FIELDS = ["image { url }", "cached_image"]

ME_QUERY = "query { me { id username } }"

BOOKS_QUERY = """
query ($uid: Int!, $start: date!, $end: date!, $max_privacy: Int!) {
  user_books(where: {
    user_id: {_eq: $uid},
    privacy_setting_id: {_lte: $max_privacy},
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

COVER_CONCURRENCY = 8
COVER_MAX_BYTES = 10 * 1024 * 1024
COVER_TIMEOUT = 15


class HardcoverError(Exception):
    """Hardcover returned an error, or couldn't be reached."""


class AuthError(HardcoverError):
    """The token is missing, invalid or expired: the user needs to sign in again."""


def new_client(**kwargs):
    """An HTTP client with our User-Agent; use one per request (or per CLI run)."""
    return httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, **kwargs)


async def gql(client, token, query, variables=None):
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    try:
        resp = await client.post(
            API_URL,
            json={"query": query, "variables": variables or {}},
            headers={"authorization": auth},
        )
    except httpx.HTTPError as e:
        raise HardcoverError(f"Couldn't reach Hardcover: {e}") from e
    if resp.status_code == 401:
        raise AuthError("Hardcover didn't accept the token; sign in again.")
    if resp.status_code != 200:
        raise HardcoverError(f"HTTP {resp.status_code} from Hardcover: {resp.text[:500]}")
    return resp.json()


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


async def fetch_me(client, token):
    """The signed-in user, as {'id': ..., 'username': ...}."""
    me = await gql(client, token, ME_QUERY)
    if me.get("errors"):
        raise HardcoverError(f"Could not identify you: {json.dumps(me['errors'])}")
    me = first(me["data"]["me"])
    if not me:
        raise AuthError("Hardcover didn't return a user for this token; sign in again.")
    return me


async def fetch_month(client, token, year, month, max_privacy=PRIVATE, debug=False):
    """Books finished in the month, oldest first, and the user's username.

    max_privacy leaves out entries more private than it: PUBLIC keeps only public
    entries, FOLLOWERS_ONLY adds followers-only ones, PRIVATE keeps everything.
    """
    me = await fetch_me(client, token)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    variables = {"uid": me["id"], "start": start.isoformat(), "end": end.isoformat(),
                 "max_privacy": max_privacy}

    last_errors = None
    for image_field in IMAGE_FIELDS:
        resp = await gql(client, token, BOOKS_QUERY.replace("%IMAGE%", image_field), variables)
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
    raise HardcoverError(f"The books query failed: {json.dumps(last_errors)}")


async def download(client, url, semaphore):
    """Fetch a cover image's bytes, or None on any failure (a placeholder is drawn instead)."""
    if not url or urlsplit(url).scheme != "https":
        return None
    async with semaphore:
        try:
            async with client.stream("GET", url, timeout=COVER_TIMEOUT) as resp:
                resp.raise_for_status()
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    data += chunk
                    if len(data) > COVER_MAX_BYTES:
                        log.warning("cover too large, skipping: %s", url)
                        return None
                return bytes(data)
        except httpx.HTTPError as e:
            log.warning("could not load cover %s: %s", url, e)
            return None


async def download_covers(client, urls):
    """Download covers in parallel; returns bytes (or None) for each URL, in order."""
    semaphore = asyncio.Semaphore(COVER_CONCURRENCY)
    return await asyncio.gather(*(download(client, u, semaphore) for u in urls))
