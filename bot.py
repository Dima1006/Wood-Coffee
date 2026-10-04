import logging

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.utils import executor

from config import BOT_TOKEN, BRANCHES, STAFF_IDS
from menu import COFFEE, TEA, MILK_DRINK, DESSERTS
from states import OrderState
from keyboards import order_status_kb, yes_no_kb
from cart import add_to_cart, clear_cart, get_cart, cart_total, remove_from_cart
from db import PAYMENT_ON_ARRIVAL, PAYMENT_ONLINE, storage

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
logger = logging.getLogger(__name__)

ARRIVAL_OPTIONS = {
    "5 min",
    "10 min",
    "15 min",
}


async def reject_blocked_customer(message: types.Message) -> bool:
    if not storage.is_customer_blocked(message.from_user.id):
        return False

    await message.answer(
        "🚫 Twoje konto zostało zablokowane po dwóch nieodebranych zamówieniach. Skontaktuj się z obsługą."
    )
    return True


# ---------- Main menu ----------
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🥤 Napoje", "🍰 Desery")
    kb.add("🛒 Koszyk")
    return kb


async def keep_branch_only(state: FSMContext):
    data = await state.get_data()
    branch = data.get("branch")
    await state.reset_data()
    if branch in BRANCHES:
        await state.update_data(branch=branch)


async def show_main_menu(message: types.Message, state: FSMContext, text="Menu główne"):
    await keep_branch_only(state)
    await state.set_state(OrderState.choosing_category.state)
    await message.answer(text, reply_markup=get_main_menu())


async def restart_branch_selection(message: types.Message, state: FSMContext):
    await state.finish()
    await state.set_state(OrderState.choosing_branch.state)
    await message.answer(
        "Sesja zamówienia wygasła. Wybierz ponownie lokal.",
        reply_markup=get_branch_menu(),
    )


# ---------- Start ----------
@dp.message_handler(commands=["start"], state="*")
async def start(message: types.Message, state: FSMContext):
    await state.finish()
    clear_cart(message.from_user.id)
    if await reject_blocked_customer(message):
        return
    await message.answer(
        "☕ Witamy w Wood Coffee!\nWybierz lokal 👇",
        reply_markup=get_branch_menu(),
    )
    await state.set_state(OrderState.choosing_branch.state)


def get_branch_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for branch in BRANCHES:
        kb.add(branch)
    return kb


# ---------- Branch selection ----------
@dp.message_handler(state=OrderState.choosing_branch)
async def choose_branch(message: types.Message, state: FSMContext):
    if message.text not in BRANCHES:
        await message.answer("Wybierz lokal za pomocą przycisków.")
        return

    await state.update_data(branch=message.text)
    await message.answer(
        f"📍 Wybrany lokal: {message.text}\nWybierz kategorię 👇",
        reply_markup=get_main_menu(),
    )
    await state.set_state(OrderState.choosing_category.state)


# ---------- Categories ----------
@dp.message_handler(state=OrderState.choosing_category)
async def categories(message: types.Message, state: FSMContext):
    if message.text == "🥤 Napoje":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Kawa", "Herbata", "Napoje mleczne", "⬅️ Wstecz")
        await message.answer("Wybierz napój:", reply_markup=kb)
        await state.set_state(OrderState.choosing_item.state)

    elif message.text == "🍰 Desery":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for d, p in DESSERTS.items():
            kb.add(f"{d} — {p} zł")
        kb.add("⬅️ Wstecz")
        await message.answer("Wybierz deser:", reply_markup=kb)
        await state.set_state(OrderState.choosing_item.state)

    elif message.text == "🛒 Koszyk":
        await open_cart(message, state)

    else:
        await message.answer("Wybierz kategorię za pomocą przycisków.")


# ---------- Item selection ----------
@dp.message_handler(state=OrderState.choosing_item)
async def pick_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        await show_main_menu(message, state)
        return

    menus = {
        "Kawa": COFFEE,
        "Herbata": TEA,
        "Napoje mleczne": MILK_DRINK,
    }

    if message.text in menus:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for name in menus[message.text]:
            kb.add(name)
        kb.add("⬅️ Wstecz")
        await message.answer("Wybierz produkt:", reply_markup=kb)
        return

    all_drinks = {**COFFEE, **TEA, **MILK_DRINK}

    if message.text in all_drinks:
        await state.update_data(temp_name=message.text)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for size in all_drinks[message.text]:
            kb.add(size)
        kb.add("⬅️ Wstecz")
        await message.answer("Wybierz rozmiar lub smak:", reply_markup=kb)
        await state.set_state(OrderState.choosing_size.state)
        return

    if " — " in message.text:
        name = message.text.split(" — ")[0]
        if name in DESSERTS:
            await state.update_data(
                temp_name=name,
                temp_size="—",
                temp_price=DESSERTS[name]
            )
            await message.answer(
                f"Dodać {name}?",
                reply_markup=yes_no_kb()
            )
            await state.set_state(OrderState.confirm_add.state)
            return

    await message.answer("Wybierz produkt za pomocą przycisków.")


# ---------- Size ----------
@dp.message_handler(state=OrderState.choosing_size)
async def pick_size(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        await show_main_menu(message, state)
        return

    data = await state.get_data()
    name = data.get("temp_name")
    all_drinks = {**COFFEE, **TEA, **MILK_DRINK}

    if name not in all_drinks:
        await restart_branch_selection(message, state)
        return

    if message.text not in all_drinks[name]:
        await message.answer("Wybierz jedną z dostępnych opcji 👇")
        return

    price = all_drinks[name][message.text]
    await state.update_data(temp_size=message.text, temp_price=price)

    await message.answer(
        f"{name} ({message.text}) — {price} zł\nDodać?",
        reply_markup=yes_no_kb()
    )
    await state.set_state(OrderState.confirm_add.state)


# ---------- Confirmation ----------
@dp.callback_query_handler(
    lambda call: call.data in {"yes", "no"},
    state=OrderState.confirm_add,
)
async def confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == "yes":
        data = await state.get_data()
        if not all(key in data for key in ("temp_name", "temp_size", "temp_price")):
            await call.answer("Wybór produktu wygasł.", show_alert=True)
            await state.finish()
            await state.set_state(OrderState.choosing_branch.state)
            await call.message.answer(
                "Wybierz ponownie lokal.",
                reply_markup=get_branch_menu(),
            )
            return

        add_to_cart(call.from_user.id, {
            "name": data["temp_name"],
            "size": data["temp_size"],
            "price": data["temp_price"]
        })
        await call.message.answer("✅ Dodano", reply_markup=get_main_menu())
    else:
        await call.message.answer("❌ Anulowano", reply_markup=get_main_menu())

    await call.answer()
    await keep_branch_only(state)
    await state.set_state(OrderState.choosing_category.state)


@dp.callback_query_handler(state=OrderState.confirm_add)
async def invalid_confirmation(call: types.CallbackQuery):
    await call.answer("Wybierz Tak lub Nie.", show_alert=True)


# ---------- Cart ----------
async def show_cart(message: types.Message) -> bool:
    cart = get_cart(message.from_user.id)

    if not cart:
        await message.answer("Twój koszyk jest pusty 🕸", reply_markup=get_main_menu())
        return False

    text = "🛒 Twój koszyk:\n\n"
    for number, i in enumerate(cart, start=1):
        text += f"{number}. {i['name']} ({i['size']}) — {i['price']} zł\n"
    text += f"\n💰 Razem: {cart_total(message.from_user.id)} zł"

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Zapłać", "⬅️ Wstecz")
    kb.add("➖ Usuń pozycję")
    await message.answer(text, reply_markup=kb)
    return True


async def open_cart(message: types.Message, state: FSMContext):
    if await show_cart(message):
        await state.set_state(OrderState.viewing_cart.state)
    else:
        await state.set_state(OrderState.choosing_category.state)


async def show_payment_methods(message: types.Message, state: FSMContext):
    if not get_cart(message.from_user.id):
        await open_cart(message, state)
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Płatność online (test)", "💵 Płatność na miejscu")
    kb.add("⬅️ Wstecz")
    await state.set_state(OrderState.choosing_payment.state)
    await message.answer("Wybierz metodę płatności:", reply_markup=kb)


@dp.message_handler(state=OrderState.viewing_cart)
async def cart_actions(message: types.Message, state: FSMContext):
    if message.text == "💳 Zapłać":
        if await reject_blocked_customer(message):
            return
        await show_payment_methods(message, state)
        return

    if message.text == "➖ Usuń pozycję":
        if not get_cart(message.from_user.id):
            await open_cart(message, state)
            return

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ Wstecz")
        await state.set_state(OrderState.choosing_item_to_remove.state)
        await message.answer("Podaj numer pozycji do usunięcia:", reply_markup=kb)
        return

    if message.text == "⬅️ Wstecz":
        await show_main_menu(message, state)
        return

    if message.text == "🛒 Koszyk":
        await open_cart(message, state)
        return

    await message.answer("Wybierz Zapłać, Usuń pozycję lub Wstecz.")


@dp.message_handler(state=OrderState.choosing_item_to_remove)
async def remove_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        await open_cart(message, state)
        return

    try:
        item_number = int(message.text)
    except (TypeError, ValueError):
        await message.answer("Podaj numer pozycji z koszyka.")
        return

    removed_item = remove_from_cart(message.from_user.id, item_number - 1)
    if removed_item is None:
        await message.answer("W koszyku nie ma pozycji o tym numerze. Spróbuj ponownie.")
        return

    await message.answer(f"✅ Usunięto: {removed_item['name']} ({removed_item['size']})")
    await open_cart(message, state)


# ---------- Payment ----------
@dp.message_handler(state=OrderState.choosing_payment)
async def choose_payment_method(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        await open_cart(message, state)
        return

    payment_methods = {
        "💳 Płatność online (test)": PAYMENT_ONLINE,
        "💵 Płatność na miejscu": PAYMENT_ON_ARRIVAL,
    }
    payment_method = payment_methods.get(message.text)
    if not payment_method:
        await message.answer("Wybierz metodę płatności za pomocą przycisków.")
        return

    await state.update_data(payment_method=payment_method)
    if payment_method == PAYMENT_ONLINE:
        await message.answer("✅ Płatność online zakończona powodzeniem (test)")
    else:
        await message.answer("💵 Zapłacisz na miejscu.")

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("5 min", "10 min", "15 min")
    kb.add("⬅️ Wstecz")
    await state.set_state(OrderState.choosing_time.state)
    await message.answer("Za ile minut będziesz na miejscu?", reply_markup=kb)


# ---------- Arrival time ----------
@dp.message_handler(state=OrderState.choosing_time)
async def time_handler(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        await show_payment_methods(message, state)
        return

    if message.text not in ARRIVAL_OPTIONS:
        await message.answer("Wybierz 5, 10 lub 15 minut za pomocą przycisków.")
        return

    arrival = message.text
    await state.update_data(arrival_time=arrival)
    await state.set_state(OrderState.entering_customer_name.state)
    await message.answer(
        "Podaj imię do zamówienia.",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("⬅️ Wstecz"),
    )


# ---------- Customer name and order creation ----------
@dp.message_handler(state=OrderState.entering_customer_name)
async def customer_name_handler(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Wstecz":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("5 min", "10 min", "15 min")
        kb.add("⬅️ Wstecz")
        await state.set_state(OrderState.choosing_time.state)
        await message.answer("Za ile minut będziesz na miejscu?", reply_markup=kb)
        return

    customer_name = (message.text or "").strip()
    if not customer_name or len(customer_name) > 100:
        await message.answer("Podaj imię o długości od 1 do 100 znaków.")
        return

    cart = get_cart(message.from_user.id)
    data = await state.get_data()
    payment_method = data.get("payment_method")
    branch = data.get("branch")
    arrival = data.get("arrival_time")

    if not payment_method or not cart or branch not in BRANCHES:
        await restart_branch_selection(message, state)
        return

    if await reject_blocked_customer(message):
        await state.finish()
        clear_cart(message.from_user.id)
        return

    order = "\n".join([f"- {i['name']} ({i['size']})" for i in cart])
    total = cart_total(message.from_user.id)
    try:
        order_id = storage.create_order(
            user_id=message.from_user.id,
            items=cart,
            total=total,
            payment_method=payment_method,
            arrival_time=arrival,
            branch=branch,
            customer_name=customer_name,
        )
    except Exception:
        logger.exception("Failed to create an order for customer %s", message.from_user.id)
        await message.answer("Nie udało się utworzyć zamówienia. Spróbuj ponownie.")
        return

    payment_label = "Płatność online (test)" if payment_method == PAYMENT_ONLINE else "Płatność na miejscu"
    msg = (
        f"🔔 NOWE ZAMÓWIENIE #{order_id}\n"
        f"👤 Imię: {customer_name}\n"
        f"🆔 ID klienta: {message.from_user.id}\n"
        f"📍 Lokal: {branch}\n"
        f"💳 Płatność: {payment_label}\n"
        f"⏰ Przyjazd: za {arrival}\n\n{order}\n\n💰 Razem: {total} zł"
    )

    for staff in STAFF_IDS:
        reply_markup = order_status_kb(
            order_id, allow_no_show=payment_method == PAYMENT_ON_ARRIVAL
        )
        try:
            await bot.send_message(staff, msg, reply_markup=reply_markup)
        except Exception:
            logger.exception("Failed to notify staff member %s about order %s", staff, order_id)

    clear_cart(message.from_user.id)
    await keep_branch_only(state)
    await state.set_state(OrderState.choosing_category.state)
    await message.answer(
        f"✅ Zamówienie przyjęte. Przyjazd za {arrival}\n📍 {branch}",
        reply_markup=get_main_menu(),
    )


async def clear_order_controls(call: types.CallbackQuery, order_id: int):
    try:
        await call.message.edit_reply_markup()
    except Exception:
        logger.exception("Failed to clear controls for order %s", order_id)


@dp.callback_query_handler(lambda call: call.data and call.data.startswith("order:"), state="*")
async def process_order_status(call: types.CallbackQuery):
    if call.from_user.id not in STAFF_IDS:
        await call.answer("Tylko obsługa może zmieniać status zamówienia.", show_alert=True)
        return

    try:
        _, order_id_text, action = call.data.split(":")
        order_id = int(order_id_text)
    except (ValueError, AttributeError):
        await call.answer("Nieprawidłowa operacja.", show_alert=True)
        return

    if action == "arrived":
        if not storage.mark_arrived(order_id):
            await call.answer("To zamówienie zostało już obsłużone.", show_alert=True)
            return
        await clear_order_controls(call, order_id)
        await call.answer("Zamówienie oznaczono jako odebrane.")
        return

    if action == "no_show":
        result = storage.mark_no_show(order_id)
        if result is None:
            await call.answer("To zamówienie zostało już obsłużone.", show_alert=True)
            return

        warning_count, is_blocked = result
        customer_id = storage.get_order_customer_id(order_id)
        if customer_id is not None:
            if is_blocked:
                customer_message = (
                    "🚫 Twoje konto zostało zablokowane po dwóch nieodebranych zamówieniach. "
                    "Skontaktuj się z obsługą."
                )
            else:
                customer_message = (
                    f"🟨 Ostrzeżenie {warning_count}/2 za nieodebrane zamówienie. "
                    "Drugie ostrzeżenie zablokuje możliwość składania zamówień."
                )
            try:
                await bot.send_message(customer_id, customer_message)
            except Exception:
                logger.exception(
                    "Failed to notify customer %s about no-show order %s",
                    customer_id,
                    order_id,
                )

        await clear_order_controls(call, order_id)
        await call.answer(f"Zapisano nieodebrane zamówienie. Ostrzeżenie {warning_count}/2.")
        return

    if action == "decline":
        await call.answer()
        state = dp.current_state(chat=call.from_user.id, user=call.from_user.id)
        await state.set_state(OrderState.entering_rejection_reason.state)
        await state.update_data(
            rejection_order_id=order_id,
            rejection_message_id=call.message.message_id,
            rejection_chat_id=call.message.chat.id,
        )
        await call.message.answer(
            f"Podaj powód odrzucenia zamówienia #{order_id}."
        )
        return

    await call.answer("Nieprawidłowa operacja.", show_alert=True)


@dp.message_handler(state=OrderState.entering_rejection_reason)
async def rejection_reason_handler(message: types.Message, state: FSMContext):
    if message.from_user.id not in STAFF_IDS:
        await state.finish()
        await message.answer("Tylko obsługa może odrzucać zamówienia.")
        return

    reason = (message.text or "").strip()
    if not reason or len(reason) > 500:
        await message.answer("Podaj powód o długości od 1 do 500 znaków.")
        return

    data = await state.get_data()
    order_id = data.get("rejection_order_id")
    if not isinstance(order_id, int) or not storage.decline_order(order_id, reason):
        await state.finish()
        await message.answer("To zamówienie zostało już obsłużone.")
        return

    customer_id = storage.get_order_customer_id(order_id)
    if customer_id is not None:
        try:
            await bot.send_message(
                customer_id,
                f"❌ Niestety zamówienie #{order_id} zostało odrzucone.\nPowód: {reason}",
            )
        except Exception:
            logger.exception("Failed to notify customer about declined order %s", order_id)

    source_message_id = data.get("rejection_message_id")
    source_chat_id = data.get("rejection_chat_id")
    if isinstance(source_message_id, int) and isinstance(source_chat_id, int):
        try:
            await bot.edit_message_reply_markup(
                chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to clear controls for declined order %s", order_id)

    await state.finish()
    await message.answer(f"Zamówienie #{order_id} odrzucono. Klient został powiadomiony.")


@dp.message_handler(commands=["unblock"], state="*")
async def unblock_customer(message: types.Message):
    if message.from_user.id not in STAFF_IDS:
        await message.answer("Tylko obsługa może odblokowywać klientów.")
        return

    try:
        user_id = int(message.get_args())
    except ValueError:
        await message.answer("Użycie: /unblock <telegram_user_id>")
        return

    storage.unblock_customer(user_id)
    await message.answer(f"Klient {user_id} został odblokowany, a ostrzeżenia wyzerowane.")


@dp.errors_handler()
async def handle_unexpected_error(update: types.Update, exception: Exception):
    logger.error(
        "Unhandled exception while processing update %s",
        update.update_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )

    try:
        if update.callback_query:
            await update.callback_query.answer(
                "Coś poszło nie tak. Spróbuj ponownie.",
                show_alert=True,
            )
        elif update.message:
            await update.message.answer("Coś poszło nie tak. Spróbuj ponownie lub użyj /start.")
    except Exception:
        logger.exception("Failed to report an error to the user")

    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    executor.start_polling(dp, skip_updates=True)
