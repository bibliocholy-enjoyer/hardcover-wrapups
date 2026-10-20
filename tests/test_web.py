import base64
import hashlib
import io
import json
import subprocess
import sys
from datetime import date
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PIL import Image
from starlette.testclient import TestClient

from hardcover_wrapups import api, oauth, render, seasonal, web
from hardcover_wrapups.session import Sealer

SETTINGS = web.Settings(client_id="client-123", client_secret="shh-secret",
                        session_secret="s" * 40, base_url="http://testserver")
TODAY = date(2026, 10, 20)


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (60, 90), (200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


class FakeHardcover:
    """Just enough of Hardcover's OAuth and GraphQL endpoints for the web app."""

    def __init__(self):
        self.token_requests = []
        self.revoked = []
        self.graphql_variables = []
        self.rows = [{
            "user_book_reads": [{"started_at": "2026-09-01", "finished_at": "2026-09-05"}],
            "book": {"title": "A Book", "image": {"url": "https://covers.test/a.png"},
                     "contributions": [{"author": {"name": "Someone"}}]},
        }]
        self.valid_token = "hc_at_good"
        self.token_error = None

    def __call__(self, request):
        path = request.url.path
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "issuer": "https://api.hardcover.app",
                "authorization_endpoint": "https://hardcover.app/oauth2/authorize",
                "token_endpoint": "https://api.hardcover.app/oauth2/token",
                "revocation_endpoint": "https://api.hardcover.app/oauth2/revoke",
            })
        if path == "/oauth2/token":
            self.token_requests.append(request)
            if self.token_error:
                return httpx.Response(401, json={"error": self.token_error})
            return httpx.Response(200, json={"access_token": self.valid_token,
                                             "refresh_token": "hc_rt_refresh",
                                             "token_type": "Bearer", "expires_in": 604800})
        if path == "/oauth2/revoke":
            form = parse_qs(request.content.decode())
            self.revoked.append((form["token"][0], form["token_type_hint"][0]))
            return httpx.Response(200)
        if path == "/v1/graphql":
            if request.headers["authorization"] != f"Bearer {self.valid_token}":
                return httpx.Response(401, json={"error": "invalid_token"})
            body = json.loads(request.content)
            if "me {" in body["query"]:
                return httpx.Response(200, json={"data": {"me": [{"id": 1, "username": "sam"}]}})
            self.graphql_variables.append(body["variables"])
            return httpx.Response(200, json={"data": {"user_books": self.rows}})
        if request.url.host == "covers.test":
            return httpx.Response(200, content=png_bytes())
        return httpx.Response(404)


@pytest.fixture
def hardcover():
    return FakeHardcover()


@pytest.fixture
def client(hardcover):
    app = web.create_app(SETTINGS, transport=httpx.MockTransport(hardcover), today=lambda: TODAY)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def sign_in(client):
    login = client.get("/login")
    params = parse_qs(urlsplit(login.headers["location"]).query)
    return client.get("/callback", params={"code": "the-code", "state": params["state"][0],
                                           "iss": "https://api.hardcover.app"})


def csrf(client):
    sealed = client.cookies.get(web.SESSION_COOKIE)
    return Sealer(SETTINGS.session_secret).unseal(sealed, 60)["csrf"]


def make_wrapup(client, **fields):
    data = {"csrf": csrf(client), "month": "9", "year": "2026", "style": "grid", **fields}
    return client.post("/wrapup", data=data)


def test_landing_page_offers_sign_in(client):
    page = client.get("/")
    assert page.status_code == 200
    assert 'href="/login"' in page.text


def test_login_redirects_to_hardcover_with_pkce(client):
    resp = client.get("/login")
    assert resp.status_code == 303
    url = urlsplit(resp.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://hardcover.app/oauth2/authorize"
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert params["client_id"] == "client-123"
    assert params["redirect_uri"] == "http://testserver/callback"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"] == "read:me:content read:library:public read:library:following"
    login = Sealer(SETTINGS.session_secret).unseal(client.cookies.get(web.LOGIN_COOKIE), 60)
    assert login["state"] == params["state"]
    assert oauth.code_challenge(login["verifier"]) == params["code_challenge"]


def test_callback_signs_in_and_revokes_refresh_token(client, hardcover):
    resp = sign_in(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wrapup"
    session = Sealer(SETTINGS.session_secret).unseal(client.cookies.get(web.SESSION_COOKIE), 60)
    assert session["token"] == "hc_at_good"
    assert session["username"] == "sam"
    assert hardcover.revoked == [("hc_rt_refresh", "refresh_token")]

    token_request = hardcover.token_requests[0]
    expected_auth = base64.b64encode(b"client-123:shh-secret").decode()
    assert token_request.headers["authorization"] == f"Basic {expected_auth}"
    form = {k: v[0] for k, v in parse_qs(token_request.content.decode()).items()}
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["redirect_uri"] == "http://testserver/callback"
    assert "code_verifier" in form


def test_session_cookie_is_encrypted(client):
    sign_in(client)
    assert "hc_at_good" not in client.cookies.get(web.SESSION_COOKIE)


@pytest.mark.parametrize("params", [
    {"code": "c", "state": "wrong", "iss": "https://api.hardcover.app"},
    {"code": "c", "iss": "https://api.hardcover.app"},
])
def test_callback_rejects_mismatched_state(client, params):
    client.get("/login")
    assert client.get("/callback", params=params).status_code == 400


def test_callback_rejects_wrong_issuer(client):
    login = client.get("/login")
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    resp = client.get("/callback", params={"code": "c", "state": state, "iss": "https://evil.test"})
    assert resp.status_code == 400


def test_callback_without_login_cookie_fails(client):
    resp = client.get("/callback", params={"code": "c", "state": "s", "iss": "https://api.hardcover.app"})
    assert resp.status_code == 400


def test_cancelled_sign_in_goes_home(client):
    resp = client.get("/callback", params={"error": "access_denied"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?cancelled=1"


def test_form_needs_a_session(client):
    resp = client.get("/wrapup")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?expired=1"


def test_form_defaults_to_last_month(client):
    sign_in(client)
    page = client.get("/wrapup")
    assert page.status_code == 200
    assert '<option value="9" selected>' in page.text
    assert 'value="2026"' in page.text
    assert "Signed in as sam" in page.text
    assert 'name="columns" value="4"' in page.text


def test_render_returns_the_image(client, hardcover):
    sign_in(client)
    resp = make_wrapup(client)
    assert resp.status_code == 200
    assert 'src="data:image/png;base64,' in resp.text
    assert 'download="wrapup-2026-09-grid.png"' in resp.text
    assert hardcover.graphql_variables[-1]["max_privacy"] == api.PUBLIC


def test_followers_only_books_are_opt_in(client, hardcover):
    sign_in(client)
    make_wrapup(client, include_followers="on")
    assert hardcover.graphql_variables[-1]["max_privacy"] == api.FOLLOWERS_ONLY


def test_render_rejects_bad_csrf_token(client):
    sign_in(client)
    resp = client.post("/wrapup", data={"csrf": "nope", "month": "9", "year": "2026", "style": "grid"})
    assert resp.status_code == 403


def test_render_validates_options(client):
    sign_in(client)
    resp = make_wrapup(client, month="13", style="sparkly")
    assert resp.status_code == 400
    assert "Month must be between 1 and 12" in resp.text
    assert "Pick one of the styles" in resp.text


def test_month_with_no_books(client, hardcover):
    hardcover.rows = []
    sign_in(client)
    resp = make_wrapup(client)
    assert resp.status_code == 200
    assert "No finished books found for September 2026" in resp.text


def test_rejected_token_signs_out(client, hardcover):
    sign_in(client)
    hardcover.valid_token = "hc_at_something_else"
    resp = make_wrapup(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?expired=1"
    assert web.SESSION_COOKIE not in client.cookies


def test_sign_out_revokes_access_token(client, hardcover):
    sign_in(client)
    resp = client.post("/logout", data={"csrf": csrf(client)})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?signed_out=1"
    assert ("hc_at_good", "access_token") in hardcover.revoked
    assert web.SESSION_COOKIE not in client.cookies


def test_security_headers(client):
    resp = client.get("/")
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


@pytest.mark.parametrize("today, expected", [
    (date(2026, 10, 20), (2026, 9)),
    (date(2026, 10, 26), (2026, 9)),
    (date(2026, 10, 27), (2026, 10)),
    (date(2026, 10, 31), (2026, 10)),
    (date(2026, 1, 3), (2025, 12)),
    (date(2028, 2, 25), (2028, 2)),  # leap year: the 25th is 4 days before the 29th
])
def test_default_month(today, expected):
    assert web.default_month(today) == expected


def test_style_choices_match_renderers():
    assert [key for key, _, _ in web.STYLE_CHOICES] == render.STYLES
    assert web.DEFAULT_STYLE == render.DEFAULT_STYLE
    assert web.MAX_COLUMNS == render.MAX_COLUMNS
    assert web.MAX_NAME_LENGTH == render.MAX_NAME_LENGTH


def test_web_app_does_not_import_pillow_at_startup():
    code = "import sys, hardcover_wrapups.web; print('PIL' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_wrong_client_secret_is_logged_with_error_code(client, hardcover, caplog):
    hardcover.token_error = "invalid_client"
    resp = sign_in(client)
    assert resp.status_code == 502
    assert "invalid_client" in caplog.text


def test_seasonal_theme_is_passed_through(client, monkeypatch):
    seen = {}
    real = render.render_style

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(render, "render_style", spy)
    sign_in(client)
    assert make_wrapup(client, style="seasonal", theme="winter").status_code == 200
    assert seen["theme"] == "winter"
    make_wrapup(client, style="seasonal", theme="auto")
    assert seen["theme"] is None


def test_unknown_theme_is_rejected(client):
    sign_in(client)
    resp = make_wrapup(client, style="seasonal", theme="monsoon")
    assert resp.status_code == 400
    assert "Pick one of the seasons" in resp.text


def test_theme_choices_match_seasonal_themes():
    assert [key for key, _ in web.THEME_CHOICES[1:]] == seasonal.THEME_NAMES


def test_very_large_month_is_capped(client, hardcover):
    hardcover.rows = hardcover.rows * (web.MAX_BOOKS + 5)
    sign_in(client)
    resp = make_wrapup(client)
    assert resp.status_code == 200
    assert f"Showing the first {web.MAX_BOOKS} of your {web.MAX_BOOKS + 5} books" in resp.text


def test_favicon_is_served(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/x-icon"
    assert "max-age" in resp.headers["cache-control"]
    assert 'rel="apple-touch-icon"' in client.get("/").text
