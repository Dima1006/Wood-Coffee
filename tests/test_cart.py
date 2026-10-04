import unittest

from cart import add_to_cart, get_cart, remove_from_cart, user_carts


class CartTests(unittest.TestCase):
    def setUp(self):
        self.user_id = 42
        user_carts.clear()
        add_to_cart(self.user_id, {"name": "Latte", "size": "Średnia", "price": 17})
        add_to_cart(self.user_id, {"name": "Americano", "size": "Mała", "price": 11})

    def tearDown(self):
        user_carts.clear()

    def test_removes_item_by_zero_based_index(self):
        removed_item = remove_from_cart(self.user_id, 1)

        self.assertEqual(removed_item["name"], "Americano")
        self.assertEqual(len(get_cart(self.user_id)), 1)

    def test_does_not_remove_item_for_invalid_index(self):
        self.assertIsNone(remove_from_cart(self.user_id, 5))
        self.assertEqual(len(get_cart(self.user_id)), 2)


if __name__ == "__main__":
    unittest.main()
