# Ahead: web ordering for cafes (MVP)

Venues register themselves, build their own menu, and receive pickup orders in a panel.
Guests find a venue, order, and pick an arrival time. No customer accounts, no payments yet.

## Run locally

```bash
cd web
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEMO_SEED=1 uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. With `DEMO_SEED=1` a demo venue (`demo@woodcoffee.pl`) is created
and its generated password is printed in the console (or set `DEMO_PASSWORD`).
Without it, register your own venue at `/register`.

Environment: `SECRET_KEY` (session signing, set it in production), `DATABASE_PATH` (default `web/data/app.db`).

## GitHub Actions demo

Actions → "Run web demo" → Run workflow. The public URL appears in the run summary.
Optional repository secrets: `DEMO_PASSWORD`, `SECRET_KEY`. Cancel the run to stop the site.

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | All routes: public pages, ordering, venue panel |
| `app/db.py` | SQLite schema and connection |
| `app/utils.py` | Password hashing, price parsing, slugs (no web imports) |
| `app/seed.py` | Demo venue built from the old bot menu |
| `app/templates/`, `app/static/` | Pages, CSS, cart and panel JavaScript |

## Not in the MVP (on purpose)

Customer accounts, Google sign-in, email notifications, online payments, multiple branches per venue,
menu photos, no-show blocking, rate limiting and CSRF tokens (the session cookie is SameSite=Lax).
