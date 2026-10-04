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
        "🚫 Your account is blocked after two no-show orders. Please contact the staff."
    )
    return True


# ---------- Main menu ----------
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🥤 Drink", "🍰 Dessert")
    kb.add("🛒 Cart")
    return kb


async def keep_branch_only(state: FSMContext):
    data = await state.get_data()
    branch = data.get("branch")
    await state.reset_data()
    if branch in BRANCHES:
        await state.update_data(branch=branch)


async def show_main_menu(message: types.Message, state: FSMContext, text="Main menu"):
    await keep_branch_only(state)
    await state.set_state(OrderState.choosing_category.state)
    await message.answer(text, reply_markup=get_main_menu())


async def restart_branch_selection(message: types.Message, state: FSMContext):
    await state.finish()
    await state.set_state(OrderState.choosing_branch.state)
    await message.answer(
        "Your checkout session expired. Please choose a coffee shop again.",
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
        "☕ Welcome to Wood Coffee!\nChoose a coffee shop 👇",
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
        await message.answer("Choose a coffee shop using the buttons.")
        return

    await state.update_data(branch=message.text)
    await message.answer(
        f"📍 Selected: {message.text}\nChoose a category 👇",
        reply_markup=get_main_menu(),
    )
    await state.set_state(OrderState.choosing_category.state)


# ---------- Categories ----------
@dp.message_handler(state=OrderState.choosing_category)
async def categories(message: types.Message, state: FSMContext):
    if message.text == "🥤 Drink":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Coffee", "Tea", "Milk Drink", "⬅️ Back")
        await message.answer("Choose a drink:", reply_markup=kb)
        await state.set_state(OrderState.choosing_item.state)

    elif message.text == "🍰 Dessert":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for d, p in DESSERTS.items():
            kb.add(f"{d} — {p}₴")
        kb.add("⬅️ Back")
        await message.answer("Choose a dessert:", reply_markup=kb)
        await state.set_state(OrderState.choosing_item.state)

    elif message.text == "🛒 Cart":
        await open_cart(message, state)

    else:
        await message.answer("Choose a category using the buttons.")


# ---------- Item selection ----------
@dp.message_handler(state=OrderState.choosing_item)
async def pick_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await show_main_menu(message, state)
        return

    menus = {
        "Coffee": COFFEE,
        "Tea": TEA,
        "Milk Drink": MILK_DRINK,
    }

    if message.text in menus:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for name in menus[message.text]:
            kb.add(name)
        kb.add("⬅️ Back")
        await message.answer("Choose an item:", reply_markup=kb)
        return

    all_drinks = {**COFFEE, **TEA, **MILK_DRINK}

    if message.text in all_drinks:
        await state.update_data(temp_name=message.text)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for size in all_drinks[message.text]:
            kb.add(size)
        kb.add("⬅️ Back")
        await message.answer("Choose a size:", reply_markup=kb)
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
                f"Add {name}?",
                reply_markup=yes_no_kb()
            )
            await state.set_state(OrderState.confirm_add.state)
            return

    await message.answer("Choose an item using the buttons.")


# ---------- Size ----------
@dp.message_handler(state=OrderState.choosing_size)
async def pick_size(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await show_main_menu(message, state)
        return

    data = await state.get_data()
    name = data.get("temp_name")
    all_drinks = {**COFFEE, **TEA, **MILK_DRINK}

    if name not in all_drinks:
        await restart_branch_selection(message, state)
        return

    if message.text not in all_drinks[name]:
        await message.answer("Choose a button 👇")
        return

    price = all_drinks[name][message.text]
    await state.update_data(temp_size=message.text, temp_price=price)

    await message.answer(
        f"{name} ({message.text}) — {price}₴\nAdd it?",
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
            await call.answer("This item selection expired.", show_alert=True)
            await state.finish()
            await state.set_state(OrderState.choosing_branch.state)
            await call.message.answer(
                "Please choose a coffee shop again.",
                reply_markup=get_branch_menu(),
            )
            return

        add_to_cart(call.from_user.id, {
            "name": data["temp_name"],
            "size": data["temp_size"],
            "price": data["temp_price"]
        })
        await call.message.answer("✅ Added", reply_markup=get_main_menu())
    else:
        await call.message.answer("❌ Cancelled", reply_markup=get_main_menu())

    await call.answer()
    await keep_branch_only(state)
    await state.set_state(OrderState.choosing_category.state)


@dp.callback_query_handler(state=OrderState.confirm_add)
async def invalid_confirmation(call: types.CallbackQuery):
    await call.answer("Use Yes or No.", show_alert=True)


# ---------- Cart ----------
async def show_cart(message: types.Message) -> bool:
    cart = get_cart(message.from_user.id)

    if not cart:
        await message.answer("Your cart is empty 🕸", reply_markup=get_main_menu())
        return False

    text = "🛒 Your cart:\n\n"
    for number, i in enumerate(cart, start=1):
        text += f"{number}. {i['name']} ({i['size']}) — {i['price']}₴\n"
    text += f"\n💰 Total: {cart_total(message.from_user.id)}₴"

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Pay", "⬅️ Back")
    kb.add("➖ Remove item")
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
    kb.add("💳 Online Payment (test)", "💵 Pay on Arrival")
    kb.add("⬅️ Back")
    await state.set_state(OrderState.choosing_payment.state)
    await message.answer("Choose a payment method:", reply_markup=kb)


@dp.message_handler(state=OrderState.viewing_cart)
async def cart_actions(message: types.Message, state: FSMContext):
    if message.text == "💳 Pay":
        if await reject_blocked_customer(message):
            return
        await show_payment_methods(message, state)
        return

    if message.text == "➖ Remove item":
        if not get_cart(message.from_user.id):
            await open_cart(message, state)
            return

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ Back")
        await state.set_state(OrderState.choosing_item_to_remove.state)
        await message.answer("Enter the item number to remove:", reply_markup=kb)
        return

    if message.text == "⬅️ Back":
        await show_main_menu(message, state)
        return

    if message.text == "🛒 Cart":
        await open_cart(message, state)
        return

    await message.answer("Choose Pay, Remove item, or Back using the buttons.")


@dp.message_handler(state=OrderState.choosing_item_to_remove)
async def remove_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await open_cart(message, state)
        return

    try:
        item_number = int(message.text)
    except (TypeError, ValueError):
        await message.answer("Enter a number from the cart.")
        return

    removed_item = remove_from_cart(message.from_user.id, item_number - 1)
    if removed_item is None:
        await message.answer("There is no item with that number. Try again.")
        return

    await message.answer(f"✅ Removed: {removed_item['name']} ({removed_item['size']})")
    await open_cart(message, state)


# ---------- Payment ----------
@dp.message_handler(state=OrderState.choosing_payment)
async def choose_payment_method(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await open_cart(message, state)
        return

    payment_methods = {
        "💳 Online Payment (test)": PAYMENT_ONLINE,
        "💵 Pay on Arrival": PAYMENT_ON_ARRIVAL,
    }
    payment_method = payment_methods.get(message.text)
    if not payment_method:
        await message.answer("Choose a payment method using the buttons.")
        return

    await state.update_data(payment_method=payment_method)
    if payment_method == PAYMENT_ONLINE:
        await message.answer("✅ Online payment successful (test)")
    else:
        await message.answer("💵 You will pay when you arrive.")

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("5 min", "10 min", "15 min")
    kb.add("⬅️ Back")
    await state.set_state(OrderState.choosing_time.state)
    await message.answer("How many minutes until you arrive?", reply_markup=kb)


# ---------- Arrival time ----------
@dp.message_handler(state=OrderState.choosing_time)
async def time_handler(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await show_payment_methods(message, state)
        return

    if message.text not in ARRIVAL_OPTIONS:
        await message.answer("Choose 5, 10, or 15 minutes using the buttons.")
        return

    arrival = message.text
    await state.update_data(arrival_time=arrival)
    await state.set_state(OrderState.entering_customer_name.state)
    await message.answer(
        "Please enter the name for the order.",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("⬅️ Back"),
    )


# ---------- Customer name and order creation ----------
@dp.message_handler(state=OrderState.entering_customer_name)
async def customer_name_handler(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("5 min", "10 min", "15 min")
        kb.add("⬅️ Back")
        await state.set_state(OrderState.choosing_time.state)
        await message.answer("How many minutes until you arrive?", reply_markup=kb)
        return

    customer_name = (message.text or "").strip()
    if not customer_name or len(customer_name) > 100:
        await message.answer("Enter a name from 1 to 100 characters.")
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
        await message.answer("We could not create your order. Please try again.")
        return

    payment_label = "Online Payment (test)" if payment_method == PAYMENT_ONLINE else "Pay on Arrival"
    msg = (
        f"🔔 NEW ORDER #{order_id}\n"
        f"👤 Name: {customer_name}\n"
        f"🆔 Customer ID: {message.from_user.id}\n"
        f"📍 Coffee shop: {branch}\n"
        f"💳 Payment: {payment_label}\n"
        f"⏰ Arrival: in {arrival}\n\n{order}\n\n💰 Total: {total}₴"
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
        f"✅ We will be waiting for you in {arrival}\n📍 {branch}",
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
        await call.answer("Only staff can process orders.", show_alert=True)
        return

    try:
        _, order_id_text, action = call.data.split(":")
        order_id = int(order_id_text)
    except (ValueError, AttributeError):
        await call.answer("Invalid order action.", show_alert=True)
        return

    if action == "arrived":
        if not storage.mark_arrived(order_id):
            await call.answer("This order has already been processed.", show_alert=True)
            return
        await clear_order_controls(call, order_id)
        await call.answer("Order marked as arrived.")
        return

    if action == "no_show":
        result = storage.mark_no_show(order_id)
        if result is None:
            await call.answer("This order has already been processed.", show_alert=True)
            return

        warning_count, is_blocked = result
        customer_id = storage.get_order_customer_id(order_id)
        if customer_id is not None:
            if is_blocked:
                customer_message = (
                    "🚫 Your account has been blocked after two no-show orders. "
                    "Please contact the staff."
                )
            else:
                customer_message = (
                    f"🟨 Yellow card: this is warning {warning_count}/2 for a no-show order. "
                    "A second warning will block new orders."
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
        await call.answer(f"No-show recorded. Warning {warning_count}/2.")
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
            f"Enter the reason for declining order #{order_id}."
        )
        return

    await call.answer("Invalid order action.", show_alert=True)


@dp.message_handler(state=OrderState.entering_rejection_reason)
async def rejection_reason_handler(message: types.Message, state: FSMContext):
    if message.from_user.id not in STAFF_IDS:
        await state.finish()
        await message.answer("Only staff can decline orders.")
        return

    reason = (message.text or "").strip()
    if not reason or len(reason) > 500:
        await message.answer("Enter a reason from 1 to 500 characters.")
        return

    data = await state.get_data()
    order_id = data.get("rejection_order_id")
    if not isinstance(order_id, int) or not storage.decline_order(order_id, reason):
        await state.finish()
        await message.answer("This order has already been processed.")
        return

    customer_id = storage.get_order_customer_id(order_id)
    if customer_id is not None:
        try:
            await bot.send_message(
                customer_id,
                f"❌ Unfortunately, order #{order_id} was declined.\nReason: {reason}",
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
    await message.answer(f"Order #{order_id} declined. The customer has been notified.")


@dp.message_handler(commands=["unblock"], state="*")
async def unblock_customer(message: types.Message):
    if message.from_user.id not in STAFF_IDS:
        await message.answer("Only staff can unblock customers.")
        return

    try:
        user_id = int(message.get_args())
    except ValueError:
        await message.answer("Usage: /unblock <telegram_user_id>")
        return

    storage.unblock_customer(user_id)
    await message.answer(f"Customer {user_id} has been unblocked and their warnings were reset.")


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
                "Something went wrong. Please try again.",
                show_alert=True,
            )
        elif update.message:
            await update.message.answer("Something went wrong. Please try /start again.")
    except Exception:
        logger.exception("Failed to report an error to the user")

    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    executor.start_polling(dp, skip_updates=True)
