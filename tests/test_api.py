import asyncio
import json

import httpx
import pytest

from hardcover_wrapups import api


def run(coro):
    return asyncio.run(coro)


def fake_hardcover(handler):
    return api.new_client(transport=httpx.MockTransport(handler))


def graphql_handler(books_rows, seen):
    def handler(request):
        if request.url.host != "api.hardcover.app":
            return httpx.Response(404)
        body = json.loads(request.content)
        seen.append(body)
        if "me {" in body["query"]:
            return httpx.Response(200, json={"data": {"me": [{"id": 7, "username": "sam"}]}})
        return httpx.Response(200, json={"data": {"user_books": books_rows}})
    return handler


ROWS = [
    {"user_book_reads": [{"started_at": "2026-08-10", "finished_at": "2026-08-20"}],
     "book": {"title": "Later", "image": {"url": "https://assets.hardcover.app/b.jpg"},
              "contributions": [{"author": {"name": "A"}}, {"author": {"name": "A"}}]}},
    {"user_book_reads": [{"started_at": None, "finished_at": "2026-08-02"}],
     "book": {"title": None, "image": None, "contributions": []}},
]


async def fetch(handler, **kwargs):
    async with fake_hardcover(handler) as client:
        return await api.fetch_month(client, "hc_at_test", 2026, 12, **kwargs)


def test_fetch_month_parses_and_sorts_books():
    seen = []
    books, username = run(fetch(graphql_handler(ROWS, seen)))
    assert username == "sam"
    assert [b["title"] for b in books] == ["Untitled", "Later"]
    assert books[1]["authors"] == ["A"]
    assert books[1]["url"] == "https://assets.hardcover.app/b.jpg"
    assert books[0]["url"] is None
    variables = seen[1]["variables"]
    assert variables == {"uid": 7, "start": "2026-12-01", "end": "2027-01-01",
                         "max_privacy": api.PRIVATE}


def test_fetch_month_passes_privacy_limit():
    seen = []
    run(fetch(graphql_handler([], seen), max_privacy=api.PUBLIC))
    assert seen[1]["variables"]["max_privacy"] == api.PUBLIC


def test_bad_token_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_token"})
    with pytest.raises(api.AuthError):
        run(fetch(handler))


def test_server_error_raises_hardcover_error():
    with pytest.raises(api.HardcoverError):
        run(fetch(lambda request: httpx.Response(503, text="down")))


def test_sends_user_agent_and_bearer_token():
    seen_headers = []

    def handler(request):
        seen_headers.append(request.headers)
        return httpx.Response(200, json={"data": {"me": [{"id": 1, "username": "x"}],
                                                  "user_books": []}})
    run(fetch(handler))
    assert seen_headers[0]["authorization"] == "Bearer hc_at_test"
    assert seen_headers[0]["user-agent"] == api.USER_AGENT


def test_download_covers_keeps_order_and_skips_failures():
    def handler(request):
        if request.url.path == "/missing.jpg":
            return httpx.Response(404)
        if request.url.path == "/huge.jpg":
            return httpx.Response(200, content=b"x" * (api.COVER_MAX_BYTES + 1))
        return httpx.Response(200, content=request.url.path.encode())

    async def go():
        async with fake_hardcover(handler) as client:
            return await api.download_covers(client, [
                "https://img.test/a.jpg", None, "http://img.test/insecure.jpg",
                "https://img.test/missing.jpg", "https://img.test/huge.jpg",
                "https://img.test/b.jpg",
            ])
    assert run(go()) == [b"/a.jpg", None, None, None, None, b"/b.jpg"]


def test_download_covers_runs_in_parallel():
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, content=b"ok")

    async def go():
        async with fake_hardcover(handler) as client:
            return await api.download_covers(client, [f"https://img.test/{i}.jpg" for i in range(20)])
    assert run(go()) == [b"ok"] * 20
    assert 1 < peak <= api.COVER_CONCURRENCY
