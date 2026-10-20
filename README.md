# Hardcover Wrap-ups

Make a cover-collage image of the books you finished in a month, from your
[Hardcover](https://hardcover.app) library, ready to post wherever you like.

The goal is a public web app at `https://hardcover-wrapups.fly.dev` where you sign in
with Hardcover, pick a month and a style, and download the image. It isn't live yet;
for now there's a command-line tool.

Styles: `grid` (default), `shelf`, `cork`, `calendar`, `rainbow` and `eight`.

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

## Development

```bash
uv sync
uv run pytest
```

Code lives in `src/hardcover_wrapups/`: `api.py` talks to Hardcover's GraphQL API,
`render.py` draws the collages, and `cli.py` is the command-line tool.

## Privacy

The app is designed to be stateless: it reads your Hardcover library for one request
to draw the image and stores nothing.

## License

MIT. See [LICENSE](LICENSE). The bundled DejaVu Sans Bold font has its own permissive
license in [src/hardcover_wrapups/fonts/DejaVu-LICENSE](src/hardcover_wrapups/fonts/DejaVu-LICENSE). Book data and covers come from Hardcover and are used
under [Hardcover's API terms](https://docs.hardcover.app/api/).
