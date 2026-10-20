# Hardcover Wrap-ups

Make a cover-collage image of the books you finished in a month, from your
[Hardcover](https://hardcover.app) library, ready to post wherever you like.

The goal is a public web app at `https://hardcover-wrapups.fly.dev` where you sign in
with Hardcover, pick a month and a style, and download the image. It isn't live yet;
for now there's a command-line tool.

Styles: `grid` (default), `seasonal` (the grid with an autumn, winter, spring or summer
border, all drawn in code), `shelf`, `cork` and `calendar`.

## Command-line use

You need [uv](https://docs.astral.sh/uv/) and a personal API token from
hardcover.app → Account → API Access. Put it in a `.env` file (git ignores it):

```
HARDCOVER_TOKEN=...
```

```bash
uv run --env-file .env hc-wrapup august 2026
uv run --env-file .env hc-wrapup 8 2026 --style shelf --columns 5 --name "Sam's"
uv run --env-file .env hc-wrapup 8 2026 --privacy public   # only public library entries
uv run hc-wrapup --help
```

## Running the web app locally

Register a Hardcover developer app of type "Web app (server-side)" with the redirect URI
`http://127.0.0.1:8080/callback`, then add to `.env`:

```
HARDCOVER_CLIENT_ID=...
HARDCOVER_CLIENT_SECRET=...
SESSION_SECRET=...   # any random string of 32+ characters; it encrypts the cookies
```

```bash
uv run --env-file .env hc-wrapup-web
```

Then open http://127.0.0.1:8080 (not `localhost`, so it matches the redirect URI).
`BASE_URL`, `HOST` and `PORT` override the defaults for deployment.

## Development

```bash
uv sync
uv run pytest
```

Code lives in `src/hardcover_wrapups/`: `api.py` talks to Hardcover's GraphQL API,
`render.py` draws the collages, `cli.py` is the command-line tool, and `web.py`,
`oauth.py` and `session.py` are the web app.

## Privacy

The app is designed to be stateless: it reads your Hardcover library for one request
to draw the image and stores nothing.

## License

MIT. See [LICENSE](LICENSE). The bundled DejaVu Sans Bold font has its own permissive
license in [src/hardcover_wrapups/fonts/DejaVu-LICENSE](src/hardcover_wrapups/fonts/DejaVu-LICENSE). Book data and covers come from Hardcover and are used
under [Hardcover's API terms](https://docs.hardcover.app/api/).
