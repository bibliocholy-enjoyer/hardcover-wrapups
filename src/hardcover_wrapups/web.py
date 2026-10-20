"""The web app: sign in with Hardcover, pick a month and a style, download the image.

Stateless: the access token lives only in an encrypted cookie for SESSION_MAX_AGE,
and rendered images go straight back to the browser without being stored.

Run locally with `uv run --env-file .env hc-wrapup-web`.
"""
import asyncio
import base64
import calendar
import contextlib
import io
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.responses import FileResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from . import api, oauth
from .session import Sealer

log = logging.getLogger(__name__)

HERE = Path(__file__).parent

# Same order as render.STYLES; kept here so the form doesn't have to import Pillow.
STYLE_CHOICES = [
    ("grid", "Grid", "Covers in neat columns"),
    ("seasonal", "Seasonal", "The grid, with a border for the season"),
    ("shelf", "Shelf", "Covers standing on a wooden bookshelf"),
    ("cork", "Corkboard", "Covers pinned to a corkboard"),
    ("calendar", "Calendar", "Covers on the days you read them"),
]
DEFAULT_STYLE = "grid"

# Seasonal themes; "auto" picks the month's season (northern hemisphere).
THEME_CHOICES = [
    ("auto", "Automatic (from the month)"),
    ("autumn", "Autumn leaves"),
    ("winter", "Snowflakes"),
    ("spring", "Spring blossoms"),
    ("summer", "Summer flowers and citrus"),
]
DEFAULT_COLUMNS = 4
MAX_COLUMNS = 8
MAX_NAME_LENGTH = 40

# In the last few days of a month, people post that month's wrap-up early.
CURRENT_MONTH_DAYS = 5

LOGIN_COOKIE, LOGIN_MAX_AGE = "hcw_login", 10 * 60
SESSION_COOKIE, SESSION_MAX_AGE = "hcw_session", 15 * 60

# Rendering takes about 50 MB plus 5.5 MB per book (measured: 94 MB for 8 books,
# 271 MB for 40), so on a 512 MB machine render one image at a time and cap the
# number of books in one image. Anyone else waits a second or two.
MAX_CONCURRENT_RENDERS = 1
MAX_BOOKS = 60

MESSAGES = {
    "expired": "Your session ended. Sign in again to make another wrap-up.",
    "signed_out": "You're signed out. Nothing about your library was kept.",
    "cancelled": "Sign-in was cancelled.",
}

SECURITY_HEADERS = {
    "content-security-policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                               "script-src 'self'; form-action 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'",
    "referrer-policy": "no-referrer",
    # Browsers only honour this over HTTPS, so it's harmless on a local http:// run.
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    session_secret: str
    base_url: str = "http://127.0.0.1:8080"

    @classmethod
    def from_env(cls):
        names = {"client_id": "HARDCOVER_CLIENT_ID", "client_secret": "HARDCOVER_CLIENT_SECRET",
                 "session_secret": "SESSION_SECRET"}
        missing = [env for env in names.values() if not os.environ.get(env)]
        if missing:
            raise SystemExit(f"Missing environment variables: {', '.join(missing)}")
        values = {field: os.environ[env] for field, env in names.items()}
        if os.environ.get("BASE_URL"):
            values["base_url"] = os.environ["BASE_URL"].rstrip("/")
        return cls(**values)

    @property
    def redirect_uri(self):
        return f"{self.base_url}/callback"

    @property
    def secure_cookies(self):
        return self.base_url.startswith("https://")


@dataclass(frozen=True)
class Options:
    year: int
    month: int
    style: str = DEFAULT_STYLE
    columns: int | None = None
    name: str = ""
    include_followers: bool = False
    theme: str = "auto"

    @property
    def max_privacy(self):
        return api.FOLLOWERS_ONLY if self.include_followers else api.PUBLIC

    @property
    def filename(self):
        return f"wrapup-{self.year}-{self.month:02d}-{self.style}.png"

    @property
    def month_label(self):
        return f"{calendar.month_name[self.month]} {self.year}"


def default_month(today):
    """This month in its last CURRENT_MONTH_DAYS days, otherwise last month."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if days_in_month - today.day < CURRENT_MONTH_DAYS:
        return today.year, today.month
    last_month = today.replace(day=1) - timedelta(days=1)
    return last_month.year, last_month.month


def parse_options(form, today):
    """Options from the submitted form, and a list of problems (empty if it's valid)."""
    errors = []

    def number(field, low, high, label):
        try:
            value = int(form.get(field, ""))
        except ValueError:
            value = None
        if value is None or not low <= value <= high:
            errors.append(f"{label} must be between {low} and {high}.")
        return value

    month = number("month", 1, 12, "Month")
    year = number("year", 2000, today.year, "Year")
    style = form.get("style", DEFAULT_STYLE)
    if style not in {key for key, _, _ in STYLE_CHOICES}:
        errors.append("Pick one of the styles.")
        style = DEFAULT_STYLE
    theme = form.get("theme", "auto")
    if theme not in {key for key, _ in THEME_CHOICES}:
        errors.append("Pick one of the seasons.")
        theme = "auto"
    columns = None
    if form.get("columns", "").strip():
        columns = number("columns", 1, MAX_COLUMNS, "Books per row")
    name = " ".join(form.get("name", "").split())
    if len(name) > MAX_NAME_LENGTH:
        errors.append(f"The name can be at most {MAX_NAME_LENGTH} characters.")
        name = name[:MAX_NAME_LENGTH]
    if errors:
        return None, errors
    return Options(year=year, month=month, style=style, columns=columns, name=name,
                   include_followers=form.get("include_followers") == "on", theme=theme), []


def build_png(books, covers, options):
    """Decode covers and draw the wrap-up. CPU-bound: run it in a worker thread."""
    from . import render  # Pillow loads on the first render, so cold starts stay fast

    for book, data in zip(books, covers):
        book["image"] = render.open_cover(data)
    title = render.make_title(options.year, options.month, options.name)
    out = io.BytesIO()
    render.render_style(options.style, books, title, out, options.year, options.month,
                        columns=options.columns,
                        theme=None if options.theme == "auto" else options.theme)
    return out.getvalue()


class SecurityHeadersAndLogging:
    """Adds security headers, and logs requests without query strings (they hold codes)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start, status = time.monotonic(), 0

        async def send_with_headers(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not scope["path"].startswith("/static/"):
                    headers.setdefault("cache-control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            log.info("%s %s %s %.0fms", scope["method"], scope["path"], status,
                     (time.monotonic() - start) * 1000)


def create_app(settings, transport=None, today=date.today):
    """The Starlette app. `transport` and `today` let tests fake Hardcover and the date."""
    templates = Jinja2Templates(directory=HERE / "templates")
    sealer = Sealer(settings.session_secret)
    render_slots = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with api.new_client(transport=transport) as client:
            app.state.client = client
            app.state.provider = oauth.Provider(client, settings.client_id, settings.client_secret,
                                                settings.redirect_uri)
            yield

    def page(request, name, status=200, **context):
        return templates.TemplateResponse(request, name, context, status_code=status)

    def error_page(request, message, status):
        return page(request, "error.html", status=status, message=message)

    def set_cookie(response, name, data, max_age):
        response.set_cookie(name, sealer.seal(data), max_age=max_age, httponly=True,
                            secure=settings.secure_cookies, samesite="lax")

    def get_session(request):
        return sealer.unseal(request.cookies.get(SESSION_COOKIE), SESSION_MAX_AGE)

    def signed_out(reason):
        response = RedirectResponse(f"/?{reason}=1", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    def form_page(request, session, options, status=200, **context):
        return page(request, "wrapup.html", status=status, session=session, options=options,
                    styles=STYLE_CHOICES, themes=THEME_CHOICES, months=list(enumerate(calendar.month_name))[1:],
                    this_year=today().year, default_columns=DEFAULT_COLUMNS, max_columns=MAX_COLUMNS,
                    max_name_length=MAX_NAME_LENGTH, **context)

    async def index(request):
        message = next((text for key, text in MESSAGES.items() if key in request.query_params), None)
        return page(request, "index.html", session=get_session(request), message=message)

    async def login(request):
        state, verifier = oauth.new_state(), oauth.new_code_verifier()
        try:
            url = await request.app.state.provider.authorization_url(state, verifier)
        except api.HardcoverError:
            log.exception("couldn't start sign-in")
            return error_page(request, "Couldn't reach Hardcover. Please try again in a minute.", 502)
        response = RedirectResponse(url, status_code=303)
        set_cookie(response, LOGIN_COOKIE, {"state": state, "verifier": verifier}, LOGIN_MAX_AGE)
        return response

    async def callback(request):
        params = request.query_params
        if params.get("error") == "access_denied":
            return RedirectResponse("/?cancelled=1", status_code=303)
        if params.get("error"):
            log.warning("sign-in error from Hardcover: %s", params.get("error"))
            return error_page(request, "Hardcover couldn't complete the sign-in. Please try again.", 400)
        login_data = sealer.unseal(request.cookies.get(LOGIN_COOKIE), LOGIN_MAX_AGE)
        if not login_data or not secrets.compare_digest(params.get("state", ""), login_data["state"]):
            return error_page(request, "That sign-in link expired or didn't start here. "
                                       "Please sign in again.", 400)
        if params.get("iss") != oauth.ISSUER or not params.get("code"):
            return error_page(request, "That sign-in response wasn't from Hardcover. "
                                       "Please sign in again.", 400)

        provider, client = request.app.state.provider, request.app.state.client
        try:
            tokens = await provider.exchange_code(params["code"], login_data["verifier"])
            me = await api.fetch_me(client, tokens["access_token"])
        except api.AuthError:
            return error_page(request, "Hardcover didn't accept the sign-in. Please try again.", 400)
        except api.HardcoverError:
            log.exception("sign-in failed")
            return error_page(request, "Couldn't reach Hardcover. Please try again in a minute.", 502)

        # We never need a new access token, so cancel the refresh token straight away.
        task = None
        if tokens.get("refresh_token"):
            task = BackgroundTask(provider.revoke, tokens["refresh_token"], "refresh_token")
        response = RedirectResponse("/wrapup", status_code=303, background=task)
        set_cookie(response, SESSION_COOKIE, {
            "token": tokens["access_token"],
            "username": me.get("username"),
            "csrf": secrets.token_urlsafe(32),
        }, SESSION_MAX_AGE)
        response.delete_cookie(LOGIN_COOKIE)
        return response

    async def wrapup(request):
        session = get_session(request)
        if not session:
            return signed_out("expired")
        year, month = default_month(today())
        return form_page(request, session, Options(year=year, month=month))

    async def make_wrapup(request):
        session = get_session(request)
        if not session:
            return signed_out("expired")
        form = await request.form()
        if not secrets.compare_digest(form.get("csrf", ""), session["csrf"]):
            return error_page(request, "That form expired. Please go back and try again.", 403)
        options, errors = parse_options(form, today())
        if errors:
            year, month = default_month(today())
            return form_page(request, session, Options(year=year, month=month), status=400,
                             errors=errors)

        client = request.app.state.client
        try:
            async with render_slots:
                books, _ = await api.fetch_month(client, session["token"], options.year,
                                                 options.month, options.max_privacy)
                if not books:
                    return form_page(request, session, options, no_books=True)
                total = len(books)
                books = books[:MAX_BOOKS]
                covers = await api.download_covers(client, [b["url"] for b in books])
                png = await run_in_threadpool(build_png, books, covers, options)
        except api.AuthError:
            return signed_out("expired")
        except api.HardcoverError:
            log.exception("building a wrap-up failed")
            return error_page(request, "Couldn't get your books from Hardcover. "
                                       "Please try again in a minute.", 502)
        image = "data:image/png;base64," + base64.b64encode(png).decode()
        return form_page(request, session, options, image=image, book_count=len(books),
                         total_books=total)

    async def logout(request):
        session = get_session(request)
        form = await request.form()
        response = signed_out("signed_out")
        if session and secrets.compare_digest(form.get("csrf", ""), session["csrf"]):
            response.background = BackgroundTask(request.app.state.provider.revoke,
                                                 session["token"], "access_token")
        return response

    async def healthz(request):
        return PlainTextResponse("ok")

    async def favicon(request):  # browsers ask for /favicon.ico whatever the page links to
        return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon",
                            headers={"cache-control": "public, max-age=604800"})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/login", login),
            Route("/callback", callback),
            Route("/wrapup", wrapup),
            Route("/wrapup", make_wrapup, methods=["POST"]),
            Route("/logout", logout, methods=["POST"]),
            Route("/healthz", healthz),
            Route("/favicon.ico", favicon),
            Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
        ],
        middleware=[Middleware(SecurityHeadersAndLogging)],
        lifespan=lifespan,
    )


def serve():
    """Entry point for `hc-wrapup-web`."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per cover download is noise
    uvicorn.run(create_app(Settings.from_env()), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")),
                access_log=False, server_header=False)
