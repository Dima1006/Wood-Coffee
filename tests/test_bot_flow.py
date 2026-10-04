import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["BOT_TOKEN"] = "123456:" + "A" * 35
os.environ["STAFF_IDS"] = ""

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

import bot as app
from cart import add_to_cart, get_cart, user_carts
from db import PAYMENT_ON_ARRIVAL, PAYMENT_ONLINE, OrderStorage
from states import OrderState


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    USER_ID = 42

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.order_storage = OrderStorage(Path(self.temp_dir.name) / "orders.db")
        self.fsm_storage = MemoryStorage()

        self.original_order_storage = app.storage
        self.original_fsm_storage = app.dp.storage
        self.original_staff_ids = app.STAFF_IDS
        app.storage = self.order_storage
        app.dp.storage = self.fsm_storage
        app.STAFF_IDS = []
        user_carts.clear()

        self.send_message = AsyncMock(return_value=None)
        self.answer_callback = AsyncMock(return_value=None)
        self.edit_reply_markup = AsyncMock(return_value=None)
        self.patchers = [
            patch.object(app.bot, "send_message", new=self.send_message),
            patch.object(app.bot, "answer_callback_query", new=self.answer_callback),
            patch.object(
                app.bot,
                "edit_message_reply_markup",
                new=self.edit_reply_markup,
            ),
        ]
        for patcher in self.patchers:
            patcher.start()

        Bot.set_current(app.bot)
        Dispatcher.set_current(app.dp)
        self.update_id = 0

    async def asyncTearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        user_carts.clear()
        app.storage = self.original_order_storage
        app.dp.storage = self.original_fsm_storage
        app.STAFF_IDS = self.original_staff_ids
        await self.fsm_storage.close()
        await self.fsm_storage.wait_closed()
        self.order_storage.close()
        self.temp_dir.cleanup()

    def state_for(self, user_id=None):
        user_id = user_id or self.USER_ID
        return app.dp.current_state(chat=user_id, user=user_id)

    async def set_state(self, state, user_id=None, **data):
        context = self.state_for(user_id)
        await context.set_state(state.state)
        if data:
            await context.update_data(**data)
        return context

    async def send_message_update(self, text, user_id=None):
        user_id = user_id or self.USER_ID
        self.update_id += 1
        message = types.Message(
            message_id=self.update_id,
            date=int(time.time()),
            chat=types.Chat(id=user_id, type="private"),
            text=text,
            **{
                "from": types.User(
                    id=user_id,
                    is_bot=False,
                    first_name="Test customer",
                )
            },
        )
        update = types.Update(update_id=self.update_id, message=message)
        await asyncio.create_task(app.dp.process_update(update))

    async def send_callback_update(self, data, user_id=None):
        user_id = user_id or self.USER_ID
        self.update_id += 1
        user = types.User(id=user_id, is_bot=False, first_name="Test customer")
        message = types.Message(
            message_id=self.update_id,
            date=int(time.time()),
            chat=types.Chat(id=user_id, type="private"),
            text="callback source",
            **{"from": user},
        )
        callback = types.CallbackQuery(
            id=str(self.update_id),
            chat_instance="test-chat",
            message=message,
            data=data,
            **{"from": user},
        )
        update = types.Update(update_id=self.update_id, callback_query=callback)
        await asyncio.create_task(app.dp.process_update(update))

    def add_test_item(self, user_id=None, name="Latte"):
        user_id = user_id or self.USER_ID
        add_to_cart(
            user_id,
            {"name": name, "size": "Średnia", "price": 17},
        )

    def response_texts(self):
        texts = []
        for call in self.send_message.await_args_list:
            if "text" in call.kwargs:
                texts.append(call.kwargs["text"])
            elif len(call.args) > 1:
                texts.append(call.args[1])
        return texts

    async def test_warsaw_polish_localization(self):
        self.assertEqual(
            app.BRANCHES,
            (
                "Wood Coffee — ul. Nowy Świat 28",
                "Wood Coffee — ul. Marszałkowska 84/92",
                "Wood Coffee — ul. Mokotowska 17",
            ),
        )
        self.assertEqual(app.COFFEE["Latte"]["Średnia"], 17)

        menu_buttons = {
            getattr(button, "text", button)
            for row in app.get_main_menu().keyboard
            for button in row
        }
        self.assertEqual(menu_buttons, {"🥤 Napoje", "🍰 Desery", "🛒 Koszyk"})

        self.add_test_item()
        await self.set_state(OrderState.choosing_category, branch=app.BRANCHES[0])
        await self.send_message_update("🛒 Koszyk")
        self.assertTrue(any("17 zł" in text for text in self.response_texts()))

    async def test_complete_order_flow_from_start(self):
        state = self.state_for()

        await self.send_message_update("/start")
        self.assertEqual(await state.get_state(), OrderState.choosing_branch.state)

        await self.send_message_update(app.BRANCHES[0])
        await self.send_message_update("🥤 Napoje")
        await self.send_message_update("Kawa")
        await self.send_message_update("Latte")
        await self.send_message_update("Średnia")
        self.assertEqual(await state.get_state(), OrderState.confirm_add.state)

        await self.send_callback_update("yes")
        self.assertEqual(len(get_cart(self.USER_ID)), 1)
        await self.send_message_update("🛒 Koszyk")
        await self.send_message_update("💳 Zapłać")
        await self.send_message_update("💳 Płatność online (test)")
        await self.send_message_update("10 min")
        self.assertEqual(await state.get_state(), OrderState.entering_customer_name.state)
        await self.send_message_update("Alex")

        order = self.order_storage.connection.execute(
            "SELECT user_id, customer_name, total, payment_method, branch FROM orders"
        ).fetchone()
        self.assertEqual(order["user_id"], self.USER_ID)
        self.assertEqual(order["customer_name"], "Alex")
        self.assertEqual(order["total"], 17)
        self.assertEqual(order["payment_method"], PAYMENT_ONLINE)
        self.assertEqual(order["branch"], app.BRANCHES[0])
        self.assertEqual(await state.get_state(), OrderState.choosing_category.state)

    async def test_cart_routes_pay_and_back_without_being_swallowed(self):
        self.add_test_item()
        state = await self.set_state(
            OrderState.choosing_category,
            branch=app.BRANCHES[0],
        )

        await self.send_message_update("🛒 Koszyk")
        self.assertEqual(await state.get_state(), OrderState.viewing_cart.state)

        await self.send_message_update("💳 Zapłać")
        self.assertEqual(await state.get_state(), OrderState.choosing_payment.state)
        self.assertIn("Wybierz metodę płatności:", self.response_texts())

        await self.send_message_update("⬅️ Wstecz")
        self.assertEqual(await state.get_state(), OrderState.viewing_cart.state)

        await self.send_message_update("⬅️ Wstecz")
        self.assertEqual(await state.get_state(), OrderState.choosing_category.state)

    async def test_remove_item_validates_input_and_handles_empty_cart(self):
        self.add_test_item(name="Latte")
        self.add_test_item(name="Cappuccino")
        state = await self.set_state(
            OrderState.viewing_cart,
            branch=app.BRANCHES[0],
        )

        await self.send_message_update("➖ Usuń pozycję")
        self.assertEqual(
            await state.get_state(),
            OrderState.choosing_item_to_remove.state,
        )

        await self.send_message_update("not a number")
        await self.send_message_update("99")
        self.assertEqual(len(get_cart(self.USER_ID)), 2)
        self.assertIn("Podaj numer pozycji z koszyka.", self.response_texts())
        self.assertIn("W koszyku nie ma pozycji o tym numerze. Spróbuj ponownie.", self.response_texts())

        await self.send_message_update("2")
        self.assertEqual(len(get_cart(self.USER_ID)), 1)
        self.assertEqual(await state.get_state(), OrderState.viewing_cart.state)

        await self.send_message_update("➖ Usuń pozycję")
        await self.send_message_update("1")
        self.assertEqual(get_cart(self.USER_ID), [])
        self.assertEqual(await state.get_state(), OrderState.choosing_category.state)

    async def test_both_payment_methods_complete_and_allow_a_new_order(self):
        for offset, (button, expected_method) in enumerate(
            (
                ("💳 Płatność online (test)", PAYMENT_ONLINE),
                ("💵 Płatność na miejscu", PAYMENT_ON_ARRIVAL),
            )
        ):
            user_id = self.USER_ID + offset
            self.add_test_item(user_id=user_id)
            state = await self.set_state(
                OrderState.viewing_cart,
                user_id=user_id,
                branch=app.BRANCHES[0],
            )

            await self.send_message_update("💳 Zapłać", user_id=user_id)
            await self.send_message_update(button, user_id=user_id)
            self.assertEqual(await state.get_state(), OrderState.choosing_time.state)

            await self.send_message_update("7 min", user_id=user_id)
            self.assertEqual(await state.get_state(), OrderState.choosing_time.state)

            await self.send_message_update("⬅️ Wstecz", user_id=user_id)
            self.assertEqual(await state.get_state(), OrderState.choosing_payment.state)
            await self.send_message_update(button, user_id=user_id)
            await self.send_message_update("5 min", user_id=user_id)
            await self.send_message_update(f"Klient {user_id}", user_id=user_id)

            row = self.order_storage.connection.execute(
                "SELECT payment_method FROM orders WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            self.assertEqual(row["payment_method"], expected_method)
            self.assertEqual(get_cart(user_id), [])
            self.assertEqual(await state.get_state(), OrderState.choosing_category.state)
            self.assertEqual((await state.get_data())["branch"], app.BRANCHES[0])

            await self.send_message_update("🥤 Napoje", user_id=user_id)
            self.assertEqual(await state.get_state(), OrderState.choosing_item.state)

    async def test_unknown_text_gets_a_response_in_every_message_state(self):
        cases = (
            (OrderState.choosing_branch, {}, "unexpected input"),
            (OrderState.choosing_category, {"branch": app.BRANCHES[0]}, "unexpected input"),
            (OrderState.choosing_item, {"branch": app.BRANCHES[0]}, "unexpected input"),
            (
                OrderState.choosing_size,
                {"branch": app.BRANCHES[0], "temp_name": "Latte"},
                "unexpected input",
            ),
            (OrderState.viewing_cart, {"branch": app.BRANCHES[0]}, "unexpected input"),
            (OrderState.choosing_item_to_remove, {"branch": app.BRANCHES[0]}, "unexpected input"),
            (OrderState.choosing_payment, {"branch": app.BRANCHES[0]}, "unexpected input"),
            (
                OrderState.choosing_time,
                {
                    "branch": app.BRANCHES[0],
                    "payment_method": PAYMENT_ONLINE,
                },
                "unexpected input",
            ),
            (
                OrderState.entering_customer_name,
                {
                    "branch": app.BRANCHES[0],
                    "payment_method": PAYMENT_ONLINE,
                    "arrival_time": "12:30",
                },
                "x" * 101,
            ),
        )

        for state_value, data, invalid_input in cases:
            with self.subTest(state=state_value.state):
                self.add_test_item()
                state = await self.set_state(state_value, **data)
                before = self.send_message.await_count
                await self.send_message_update(invalid_input)
                self.assertGreater(self.send_message.await_count, before)
                self.assertEqual(await state.get_state(), state_value.state)
                user_carts.clear()

    async def test_confirmation_accepts_only_yes_or_no(self):
        state = await self.set_state(
            OrderState.confirm_add,
            branch=app.BRANCHES[0],
            temp_name="Latte",
            temp_size="Średnia",
            temp_price=17,
        )

        await self.send_callback_update("maybe")
        self.assertEqual(await state.get_state(), OrderState.confirm_add.state)
        self.assertEqual(get_cart(self.USER_ID), [])

        await self.send_callback_update("yes")
        self.assertEqual(await state.get_state(), OrderState.choosing_category.state)
        self.assertEqual(len(get_cart(self.USER_ID)), 1)

    async def test_staff_notification_failure_does_not_break_customer_flow(self):
        app.STAFF_IDS = [999]

        async def fail_for_staff(chat_id, text, **kwargs):
            if chat_id == 999:
                raise RuntimeError("staff delivery failed")
            return None

        self.send_message.side_effect = fail_for_staff
        self.add_test_item()
        state = await self.set_state(
            OrderState.choosing_time,
            branch=app.BRANCHES[0],
            payment_method=PAYMENT_ON_ARRIVAL,
        )

        with self.assertLogs(app.logger, level="ERROR") as captured_logs:
            await self.send_message_update("5 min")
            await self.send_message_update("Alex")

        order_count = self.order_storage.connection.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ?",
            (self.USER_ID,),
        ).fetchone()[0]
        self.assertEqual(order_count, 1)
        self.assertEqual(get_cart(self.USER_ID), [])
        self.assertEqual(await state.get_state(), OrderState.choosing_category.state)
        self.assertTrue(
            any(text.startswith("✅ Zamówienie przyjęte") for text in self.response_texts())
        )
        self.assertTrue(
            any("Failed to notify staff member 999" in line for line in captured_logs.output)
        )

    async def test_arrival_options_are_stored_as_relative_values(self):
        for offset, arrival in enumerate(("5 min", "10 min", "15 min")):
            user_id = self.USER_ID + offset
            self.add_test_item(user_id=user_id)
            state = await self.set_state(
                OrderState.choosing_time,
                user_id=user_id,
                branch=app.BRANCHES[0],
                payment_method=PAYMENT_ON_ARRIVAL,
            )

            await self.send_message_update(arrival, user_id=user_id)
            self.assertEqual(
                await state.get_state(),
                OrderState.entering_customer_name.state,
            )
            await self.send_message_update("Alex", user_id=user_id)

            stored_arrival = self.order_storage.connection.execute(
                "SELECT arrival_time FROM orders WHERE user_id = ?",
                (user_id,),
            ).fetchone()["arrival_time"]
            self.assertEqual(stored_arrival, arrival)
            self.assertTrue(
                any(
                    text.startswith(f"✅ Zamówienie przyjęte. Przyjazd za {arrival}")
                    for text in self.response_texts()
                )
            )

    async def test_database_failure_keeps_cart_and_name_step(self):
        self.add_test_item()
        state = await self.set_state(
            OrderState.entering_customer_name,
            branch=app.BRANCHES[0],
            payment_method=PAYMENT_ON_ARRIVAL,
            arrival_time="10 min",
        )

        with patch.object(
            self.order_storage,
            "create_order",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertLogs(app.logger, level="ERROR"):
                await self.send_message_update("Alex")

        self.assertEqual(await state.get_state(), OrderState.entering_customer_name.state)
        self.assertEqual(len(get_cart(self.USER_ID)), 1)
        self.assertIn(
            "Nie udało się utworzyć zamówienia. Spróbuj ponownie.",
            self.response_texts(),
        )

    async def test_blocked_customer_cannot_start_payment(self):
        for _ in range(2):
            order_id = self.order_storage.create_order(
                user_id=self.USER_ID,
                items=[{"name": "Latte", "size": "Średnia", "price": 17}],
                total=17,
                payment_method=PAYMENT_ON_ARRIVAL,
                arrival_time="12:30",
                branch=app.BRANCHES[0],
            )
            self.order_storage.mark_no_show(order_id)

        self.add_test_item()
        state = await self.set_state(
            OrderState.viewing_cart,
            branch=app.BRANCHES[0],
        )
        await self.send_message_update("💳 Zapłać")

        self.assertEqual(await state.get_state(), OrderState.viewing_cart.state)
        self.assertTrue(any("zablokowane" in text for text in self.response_texts()))

    async def test_staff_status_callback_is_routed_and_processed(self):
        app.STAFF_IDS = [self.USER_ID]
        order_id = self.order_storage.create_order(
            user_id=100,
            items=[{"name": "Latte", "size": "Średnia", "price": 17}],
            total=17,
            payment_method=PAYMENT_ON_ARRIVAL,
            arrival_time="12:30",
            branch=app.BRANCHES[0],
        )

        await self.send_callback_update(f"order:{order_id}:arrived")

        status = self.order_storage.connection.execute(
            "SELECT status FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()["status"]
        self.assertEqual(status, "arrived")
        self.edit_reply_markup.assert_awaited_once()
        self.answer_callback.assert_awaited_once()

        await self.send_callback_update(f"order:{order_id}:arrived")
        self.assertEqual(
            self.order_storage.connection.execute(
                "SELECT status FROM orders WHERE id = ?", (order_id,)
            ).fetchone()["status"],
            "arrived",
        )
        self.assertTrue(self.answer_callback.await_args.kwargs["show_alert"])

    async def test_no_show_notification_failure_does_not_break_staff_action(self):
        app.STAFF_IDS = [self.USER_ID]
        order_id = self.order_storage.create_order(
            user_id=100,
            items=[{"name": "Latte", "size": "Średnia", "price": 17}],
            total=17,
            payment_method=PAYMENT_ON_ARRIVAL,
            arrival_time="10 min",
            branch=app.BRANCHES[0],
        )

        self.send_message.side_effect = RuntimeError("customer unavailable")
        with self.assertLogs(app.logger, level="ERROR") as captured_logs:
            await self.send_callback_update(f"order:{order_id}:no_show")

        status = self.order_storage.connection.execute(
            "SELECT status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()["status"]
        self.assertEqual(status, "no_show")
        self.edit_reply_markup.assert_awaited_once()
        self.answer_callback.assert_awaited_once()
        self.assertTrue(
            any("Failed to notify customer 100" in line for line in captured_logs.output)
        )

    async def test_staff_can_decline_order_with_reason(self):
        app.STAFF_IDS = [self.USER_ID]
        order_id = self.order_storage.create_order(
            user_id=100,
            items=[{"name": "Latte", "size": "Średnia", "price": 17}],
            total=17,
            payment_method=PAYMENT_ONLINE,
            arrival_time="12:30",
            branch=app.BRANCHES[0],
            customer_name="Alex",
        )

        await self.send_callback_update(f"order:{order_id}:decline")
        self.assertEqual(
            await self.state_for().get_state(),
            OrderState.entering_rejection_reason.state,
        )
        await self.send_message_update("We are closing early.")

        order = self.order_storage.connection.execute(
            "SELECT status, rejection_reason FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        self.assertEqual(order["status"], "declined")
        self.assertEqual(order["rejection_reason"], "We are closing early.")
        self.assertTrue(
            any(
                call.args[0] == 100 and "We are closing early." in call.args[1]
                for call in self.send_message.await_args_list
                if len(call.args) > 1
            )
        )


if __name__ == "__main__":
    unittest.main()
