import tempfile
import unittest
import sqlite3
from pathlib import Path

from db import PAYMENT_ON_ARRIVAL, PAYMENT_ONLINE, OrderStorage


class OrderStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = OrderStorage(Path(self.temp_dir.name) / "test.db")

    def tearDown(self):
        self.storage.close()
        self.temp_dir.cleanup()

    def create_order(self, payment_method=PAYMENT_ON_ARRIVAL):
        return self.storage.create_order(
            user_id=42,
            items=[{"name": "Latte", "size": "Średnia", "price": 17}],
            total=17,
            payment_method=payment_method,
            arrival_time="12:30",
            branch="Wood Coffee — ul. Nowy Świat 28",
        )

    def test_order_stores_selected_branch(self):
        order_id = self.create_order()
        self.assertEqual(
            self.storage.get_order_branch(order_id), "Wood Coffee — ul. Nowy Świat 28"
        )

    def test_order_stores_customer_name_and_decline_reason(self):
        order_id = self.storage.create_order(
            user_id=42,
            items=[],
            total=0,
            payment_method=PAYMENT_ONLINE,
            arrival_time="12:30",
            branch="Wood Coffee",
            customer_name="Alex",
        )
        self.assertTrue(self.storage.decline_order(order_id, "The shop is closing."))
        order = self.storage.connection.execute(
            "SELECT customer_name, status, rejection_reason FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        self.assertEqual(order["customer_name"], "Alex")
        self.assertEqual(order["status"], "declined")
        self.assertEqual(order["rejection_reason"], "The shop is closing.")
        self.assertFalse(self.storage.decline_order(order_id, "Another reason"))

    def test_existing_database_is_migrated_with_branch_column(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    items TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            cursor = connection.execute(
                """
                INSERT INTO orders (user_id, items)
                VALUES (?, ?)
                """,
                (42, "[]"),
            )
            legacy_order_id = cursor.lastrowid

        legacy_storage = OrderStorage(legacy_path)
        try:
            columns = {
                row["name"]
                for row in legacy_storage.connection.execute("PRAGMA table_info(orders)")
            }
            self.assertTrue(
                {
                    "total",
                    "payment_method",
                    "arrival_time",
                    "branch",
                    "customer_name",
                    "rejection_reason",
                    "created_at",
                }.issubset(columns)
            )
            self.assertEqual(legacy_storage.get_order_customer_id(legacy_order_id), 42)
            self.assertEqual(legacy_storage.get_order_branch(legacy_order_id), "")
            legacy_order = legacy_storage.connection.execute(
                "SELECT total, payment_method, arrival_time FROM orders WHERE id = ?",
                (legacy_order_id,),
            ).fetchone()
            self.assertEqual(legacy_order["total"], 0)
            self.assertEqual(legacy_order["payment_method"], PAYMENT_ON_ARRIVAL)
            self.assertEqual(legacy_order["arrival_time"], "")
        finally:
            legacy_storage.close()

    def test_second_no_show_blocks_customer(self):
        self.assertEqual(self.storage.mark_no_show(self.create_order()), (1, False))
        self.assertEqual(self.storage.mark_no_show(self.create_order()), (2, True))
        self.assertTrue(self.storage.is_customer_blocked(42))

    def test_processed_order_cannot_create_another_warning(self):
        order_id = self.create_order()
        self.storage.mark_no_show(order_id)
        self.assertIsNone(self.storage.mark_no_show(order_id))

    def test_online_order_cannot_create_a_warning(self):
        self.assertIsNone(self.storage.mark_no_show(self.create_order(PAYMENT_ONLINE)))
        self.assertFalse(self.storage.is_customer_blocked(42))

    def test_arrived_order_is_not_processed_twice(self):
        order_id = self.create_order()
        self.assertTrue(self.storage.mark_arrived(order_id))
        self.assertFalse(self.storage.mark_arrived(order_id))

    def test_unblock_resets_warnings(self):
        self.storage.mark_no_show(self.create_order())
        self.storage.mark_no_show(self.create_order())
        self.storage.unblock_customer(42)
        self.assertFalse(self.storage.is_customer_blocked(42))
        self.assertEqual(self.storage.mark_no_show(self.create_order()), (1, False))


if __name__ == "__main__":
    unittest.main()
