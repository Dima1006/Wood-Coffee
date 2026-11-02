import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db as database
from .db import get_db
from .seed import seed_demo
from .utils import (format_zl, hash_password, parse_prices, prices_to_text,
                    slugify, verify_password)

BASE_DIR = Path(__file__).resolve().parent
WARSAW = ZoneInfo("Europe/Warsaw")

APP_NAME = "Ahead"  # working name: rename freely
ARRIVAL_CHOICES = (5, 10, 15, 30, 45, 60)

STATUS_LABELS = {
    "new": "New",
    "preparing": "Preparing",
    "ready": "Ready for pickup",
    "completed": "Picked up",
    "declined": "Declined",
    "no_show": "No-show",
}
ACTIVE_STATUSES = ("new", "preparing", "ready")
# status -> statuses the venue may move it to
ALLOWED = {
    "new": ("preparing", "no_show", "declined"),
    "preparing": ("ready", "no_show", "declined"),
    "ready": ("completed", "no_show", "declined"),
}
ACTION_LABELS = {
    "preparing": "Start preparing",
    "ready": "Mark ready",
    "completed": "Picked up",
    "no_show": "No-show",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    if os.getenv("DEMO_SEED") == "1":
        seed_demo()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    same_site="lax",
    max_age=14 * 24 * 3600,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["zl"] = format_zl
templates.env.globals.update(
    APP_NAME=APP_NAME,
    STATUS_LABELS=STATUS_LABELS,
    ACTION_LABELS=ACTION_LABELS,
    ALLOWED=ALLOWED,
    ARRIVAL_CHOICES=ARRIVAL_CHOICES,
)


def render(request: Request, name: str, status_code: int = 200, **ctx):
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def redirect(url: str, error: str | None = None):
    if error:
        url += ("&" if "?" in url else "?") + "error=" + quote(error)
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- auth

class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def _not_authenticated(request: Request, exc: NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


def current_venue(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    venue_id = request.session.get("venue_id")
    venue = conn.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone() if venue_id else None
    if not venue:
        request.session.clear()
        raise NotAuthenticated()
    return venue


def unique_slug(conn: sqlite3.Connection, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM venues WHERE slug = ?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


@app.get("/register")
def register_form(request: Request):
    return render(request, "register.html", error=None, form={})


@app.post("/register")
def register(request: Request, venue_name: str = Form(...), city: str = Form(""),
             email: str = Form(...), password: str = Form(...),
             conn: sqlite3.Connection = Depends(get_db)):
    venue_name, city, email = venue_name.strip()[:80], city.strip()[:60], email.strip().lower()[:120]
    form = {"venue_name": venue_name, "city": city, "email": email}
    error = None
    if not venue_name:
        error = "Enter the venue name."
    elif "@" not in email or "." not in email.split("@")[-1]:
        error = "Enter a valid email."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif conn.execute("SELECT 1 FROM venues WHERE email = ?", (email,)).fetchone():
        error = "This email is already registered."
    if error:
        return render(request, "register.html", 400, error=error, form=form)
    venue_id = conn.execute(
        "INSERT INTO venues (slug, name, city, email, password_hash) VALUES (?, ?, ?, ?, ?)",
        (unique_slug(conn, venue_name), venue_name, city, email, hash_password(password)),
    ).lastrowid
    conn.commit()
    request.session.clear()
    request.session["venue_id"] = venue_id
    return redirect("/panel/settings")


@app.get("/login")
def login_form(request: Request):
    return render(request, "login.html", error=None, email="")


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          conn: sqlite3.Connection = Depends(get_db)):
    email = email.strip().lower()
    venue = conn.execute("SELECT * FROM venues WHERE email = ?", (email,)).fetchone()
    if not venue or not verify_password(password, venue["password_hash"]):
        return render(request, "login.html", 400, error="Wrong email or password.", email=email)
    request.session.clear()
    request.session["venue_id"] = venue["id"]
    return redirect("/panel")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/")


# ---------------------------------------------------------------- menu helpers

def load_menu(conn: sqlite3.Connection, venue_id: int):
    """Categories -> items -> variants for one venue."""
    categories = [dict(c, items=[]) for c in conn.execute(
        "SELECT * FROM categories WHERE venue_id = ? ORDER BY id", (venue_id,))]
    by_cat = {c["id"]: c for c in categories}
    items = {}
    for row in conn.execute("SELECT * FROM items WHERE venue_id = ? ORDER BY id", (venue_id,)):
        item = dict(row, variants=[])
        items[row["id"]] = item
        by_cat[row["category_id"]]["items"].append(item)
    for v in conn.execute(
        "SELECT v.* FROM variants v JOIN items i ON i.id = v.item_id "
        "WHERE i.venue_id = ? ORDER BY v.id", (venue_id,)):
        items[v["item_id"]]["variants"].append(v)
    for item in items.values():
        item["prices_text"] = prices_to_text(item["variants"])
    return categories


def get_venue_or_404(conn: sqlite3.Connection, slug: str):
    venue = conn.execute("SELECT * FROM venues WHERE slug = ?", (slug,)).fetchone()
    if not venue:
        raise HTTPException(404, "Venue not found")
    return venue


# ---------------------------------------------------------------- public pages

@app.get("/")
def home(request: Request, q: str = "", conn: sqlite3.Connection = Depends(get_db)):
    q = q.strip()[:60]
    like = f"%{q}%"
    rows = conn.execute(
        """
        SELECT v.*, (SELECT COUNT(*) FROM items i
                     WHERE i.venue_id = v.id AND i.is_available = 1) AS item_count
        FROM venues v
        WHERE v.name LIKE ? OR v.city LIKE ? OR v.address LIKE ?
        ORDER BY v.accepting_orders DESC, v.name
        """,
        (like, like, like),
    ).fetchall()
    return render(request, "home.html", q=q, venues=[v for v in rows if v["item_count"]])


def venue_context(conn, venue, error=None, form=None):
    menu = [c for c in load_menu(conn, venue["id"]) if c["items"]]
    menu_data = {
        str(v["id"]): {"name": item["name"], "label": v["label"], "price": v["price"]}
        for c in menu for item in c["items"] if item["is_available"] for v in item["variants"]
    }
    return dict(venue=venue, menu=menu, menu_data=menu_data, error=error, form=form or {})


@app.get("/v/{slug}")
def venue_page(request: Request, slug: str, conn: sqlite3.Connection = Depends(get_db)):
    venue = get_venue_or_404(conn, slug)
    return render(request, "venue.html", **venue_context(conn, venue))


@app.post("/v/{slug}/order")
def place_order(request: Request, slug: str,
                customer_name: str = Form(...), phone: str = Form(""),
                arrival_minutes: int = Form(...), note: str = Form(""),
                cart: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    venue = get_venue_or_404(conn, slug)
    form = {"name": customer_name, "phone": phone, "note": note, "arrival": arrival_minutes}

    def fail(message: str):
        return render(request, "venue.html", 400, **venue_context(conn, venue, message, form))

    customer_name, phone, note = customer_name.strip()[:60], phone.strip()[:30], note.strip()[:300]
    if not venue["accepting_orders"]:
        return fail("This venue is not accepting orders right now.")
    if not customer_name:
        return fail("Please enter your name.")
    if arrival_minutes not in ARRIVAL_CHOICES:
        return fail("Choose when you will arrive.")

    # Never trust prices from the browser: only variant ids and quantities are used.
    wanted: dict[int, int] = {}
    try:
        for line in json.loads(cart)[:50]:
            vid, qty = int(line["variant_id"]), int(line["qty"])
            if 1 <= qty <= 20:
                wanted[vid] = wanted.get(vid, 0) + qty
    except (ValueError, TypeError, KeyError):
        return fail("Your cart could not be read. Please try again.")
    if not wanted:
        return fail("Your cart is empty.")

    marks = ",".join("?" * len(wanted))
    rows = conn.execute(
        f"""
        SELECT v.id, v.label, v.price, i.name, i.is_available
        FROM variants v JOIN items i ON i.id = v.item_id
        WHERE i.venue_id = ? AND v.id IN ({marks})
        """,
        (venue["id"], *wanted),
    ).fetchall()
    if len(rows) != len(wanted) or not all(r["is_available"] for r in rows):
        return fail("Some items in your cart are no longer available. Please review your order.")

    total = sum(r["price"] * wanted[r["id"]] for r in rows)
    token = secrets.token_urlsafe(16)
    order_id = conn.execute(
        "INSERT INTO orders (venue_id, token, customer_name, phone, arrival_minutes, note, total) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (venue["id"], token, customer_name, phone, arrival_minutes, note, total),
    ).lastrowid
    conn.executemany(
        "INSERT INTO order_items (order_id, name, variant_label, price, qty) VALUES (?, ?, ?, ?, ?)",
        [(order_id, r["name"], r["label"], r["price"], wanted[r["id"]]) for r in rows],
    )
    conn.commit()
    return redirect(f"/order/{token}")


def hydrate(conn: sqlite3.Connection, rows):
    orders = []
    for r in rows:
        o = dict(r)
        created = datetime.fromisoformat(r["created_at"]).replace(tzinfo=timezone.utc).astimezone(WARSAW)
        o["items"] = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (r["id"],)).fetchall()
        o["created_local"] = created.strftime("%H:%M")
        o["arrival_local"] = (created + timedelta(minutes=r["arrival_minutes"])).strftime("%H:%M")
        o["status_label"] = STATUS_LABELS[r["status"]]
        orders.append(o)
    return orders


@app.get("/order/{token}")
def order_page(request: Request, token: str, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        """
        SELECT o.*, v.name AS venue_name, v.address AS venue_address, v.slug AS venue_slug
        FROM orders o JOIN venues v ON v.id = o.venue_id WHERE o.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Order not found")
    return render(request, "order.html", order=hydrate(conn, [row])[0])


# ---------------------------------------------------------------- panel: orders

def orders_context(conn: sqlite3.Connection, venue):
    active = conn.execute(
        """
        SELECT * FROM orders WHERE venue_id = ? AND status IN ('new', 'preparing', 'ready')
        ORDER BY datetime(created_at, '+' || arrival_minutes || ' minutes')
        """,
        (venue["id"],),
    ).fetchall()
    history = conn.execute(
        """
        SELECT * FROM orders WHERE venue_id = ? AND status NOT IN ('new', 'preparing', 'ready')
        ORDER BY id DESC LIMIT 15
        """,
        (venue["id"],),
    ).fetchall()
    return dict(
        active=hydrate(conn, active),
        history=hydrate(conn, history),
        new_count=sum(1 for o in active if o["status"] == "new"),
    )


@app.get("/panel")
def panel_orders(request: Request, venue=Depends(current_venue), conn: sqlite3.Connection = Depends(get_db)):
    return render(request, "panel_orders.html", venue=venue, **orders_context(conn, venue))


@app.get("/panel/orders/fragment")
def panel_orders_fragment(request: Request, venue=Depends(current_venue),
                          conn: sqlite3.Connection = Depends(get_db)):
    return render(request, "_orders.html", venue=venue, **orders_context(conn, venue))


@app.post("/panel/orders/{order_id}/status")
def update_order_status(order_id: int, status: str = Form(...), reason: str = Form(""),
                        venue=Depends(current_venue), conn: sqlite3.Connection = Depends(get_db)):
    order = conn.execute(
        "SELECT id, status FROM orders WHERE id = ? AND venue_id = ?", (order_id, venue["id"])
    ).fetchone()
    if not order:
        raise HTTPException(404, "Order not found")
    if status in ALLOWED.get(order["status"], ()):
        reason = (reason.strip()[:200] or "Declined by the venue") if status == "declined" else ""
        conn.execute(
            "UPDATE orders SET status = ?, decline_reason = ? WHERE id = ? AND status = ?",
            (status, reason, order_id, order["status"]),
        )
        conn.commit()
    return redirect("/panel")


# ---------------------------------------------------------------- panel: menu

@app.get("/panel/menu")
def panel_menu(request: Request, error: str = "", venue=Depends(current_venue),
               conn: sqlite3.Connection = Depends(get_db)):
    return render(request, "panel_menu.html", venue=venue, menu=load_menu(conn, venue["id"]), error=error)


@app.post("/panel/menu/category")
def add_category(name: str = Form(...), venue=Depends(current_venue),
                 conn: sqlite3.Connection = Depends(get_db)):
    name = name.strip()[:60]
    if name:
        conn.execute("INSERT INTO categories (venue_id, name) VALUES (?, ?)", (venue["id"], name))
        conn.commit()
    return redirect("/panel/menu")


@app.post("/panel/menu/category/{category_id}/delete")
def delete_category(category_id: int, venue=Depends(current_venue),
                    conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM categories WHERE id = ? AND venue_id = ?", (category_id, venue["id"]))
    conn.commit()
    return redirect("/panel/menu")


def save_variants(conn: sqlite3.Connection, item_id: int, prices: list[tuple[str, int]]):
    conn.execute("DELETE FROM variants WHERE item_id = ?", (item_id,))
    conn.executemany(
        "INSERT INTO variants (item_id, label, price) VALUES (?, ?, ?)",
        [(item_id, label, price) for label, price in prices],
    )


@app.post("/panel/menu/item")
def add_item(category_id: int = Form(...), name: str = Form(...), description: str = Form(""),
             prices: str = Form(...), venue=Depends(current_venue),
             conn: sqlite3.Connection = Depends(get_db)):
    if not conn.execute("SELECT 1 FROM categories WHERE id = ? AND venue_id = ?",
                        (category_id, venue["id"])).fetchone():
        raise HTTPException(404, "Category not found")
    name = name.strip()[:80]
    if not name:
        return redirect("/panel/menu", "Enter an item name.")
    try:
        parsed = parse_prices(prices)
    except ValueError as exc:
        return redirect("/panel/menu", str(exc))
    item_id = conn.execute(
        "INSERT INTO items (venue_id, category_id, name, description) VALUES (?, ?, ?, ?)",
        (venue["id"], category_id, name, description.strip()[:200]),
    ).lastrowid
    save_variants(conn, item_id, parsed)
    conn.commit()
    return redirect("/panel/menu")


@app.post("/panel/menu/item/{item_id}")
def update_item(item_id: int, name: str = Form(...), description: str = Form(""),
                prices: str = Form(...), venue=Depends(current_venue),
                conn: sqlite3.Connection = Depends(get_db)):
    if not conn.execute("SELECT 1 FROM items WHERE id = ? AND venue_id = ?",
                        (item_id, venue["id"])).fetchone():
        raise HTTPException(404, "Item not found")
    name = name.strip()[:80]
    if not name:
        return redirect("/panel/menu", "Enter an item name.")
    try:
        parsed = parse_prices(prices)
    except ValueError as exc:
        return redirect("/panel/menu", str(exc))
    conn.execute("UPDATE items SET name = ?, description = ? WHERE id = ?",
                 (name, description.strip()[:200], item_id))
    save_variants(conn, item_id, parsed)
    conn.commit()
    return redirect("/panel/menu")


@app.post("/panel/menu/item/{item_id}/toggle")
def toggle_item(item_id: int, venue=Depends(current_venue), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE items SET is_available = 1 - is_available WHERE id = ? AND venue_id = ?",
                 (item_id, venue["id"]))
    conn.commit()
    return redirect("/panel/menu")


@app.post("/panel/menu/item/{item_id}/delete")
def delete_item(item_id: int, venue=Depends(current_venue), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM items WHERE id = ? AND venue_id = ?", (item_id, venue["id"]))
    conn.commit()
    return redirect("/panel/menu")


# ---------------------------------------------------------------- panel: settings

@app.get("/panel/settings")
def panel_settings(request: Request, saved: int = 0, venue=Depends(current_venue)):
    return render(request, "panel_settings.html", venue=venue, saved=bool(saved))


@app.post("/panel/settings")
def save_settings(name: str = Form(...), city: str = Form(""), address: str = Form(""),
                  description: str = Form(""), accepting_orders: str = Form(""),
                  venue=Depends(current_venue), conn: sqlite3.Connection = Depends(get_db)):
    name = name.strip()[:80] or venue["name"]
    conn.execute(
        "UPDATE venues SET name = ?, city = ?, address = ?, description = ?, accepting_orders = ? WHERE id = ?",
        (name, city.strip()[:60], address.strip()[:120], description.strip()[:300],
         1 if accepting_orders else 0, venue["id"]),
    )
    conn.commit()
    return redirect("/panel/settings?saved=1")
