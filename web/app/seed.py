"""Demo data: the Wood Coffee menu, so a fresh demo is never empty."""
import os
import secrets

from .db import connect
from .utils import hash_password

DEMO_EMAIL = "demo@woodcoffee.pl"

# category -> item -> {size label: price in zł}; a plain number means a single price
MENU = {
    "Coffee": {
        "Cappuccino": {"Small": 12, "Medium": 14, "Large": 16},
        "Latte": {"Small": 13, "Medium": 15, "Large": 17},
        "Americano": {"Small": 9, "Medium": 11, "Large": 13},
    },
    "Tea": {
        "Black Tea": {"Small": 8, "Medium": 10, "Large": 12},
        "Green Tea": {"Small": 8, "Medium": 10, "Large": 12},
    },
    "Milk drinks": {
        "Cocoa": {"Medium": 11, "Large": 13},
        "Milkshake": {"Strawberry": 15, "Chocolate": 15},
    },
    "Desserts": {"Croissant": 9, "Cheesecake": 15},
}


def seed_demo() -> None:
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM venues WHERE email = ?", (DEMO_EMAIL,)).fetchone():
            return
        password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(9)
        cur = conn.execute(
            "INSERT INTO venues (slug, name, city, address, description, email, password_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("wood-coffee", "Wood Coffee", "Warszawa", "ul. Przykładowa 1",
             "Demo venue: coffee, tea and desserts for pickup.", DEMO_EMAIL, hash_password(password)),
        )
        venue_id = cur.lastrowid
        for category, items in MENU.items():
            cat_id = conn.execute(
                "INSERT INTO categories (venue_id, name) VALUES (?, ?)", (venue_id, category)
            ).lastrowid
            for name, prices in items.items():
                item_id = conn.execute(
                    "INSERT INTO items (venue_id, category_id, name) VALUES (?, ?, ?)",
                    (venue_id, cat_id, name),
                ).lastrowid
                variants = prices.items() if isinstance(prices, dict) else [("", prices)]
                for label, zl in variants:
                    conn.execute(
                        "INSERT INTO variants (item_id, label, price) VALUES (?, ?, ?)",
                        (item_id, label, zl * 100),
                    )
        conn.commit()
        print(f"[demo] venue login: {DEMO_EMAIL} / {password}", flush=True)
    finally:
        conn.close()
