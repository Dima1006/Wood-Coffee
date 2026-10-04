from datetime import datetime, timedelta
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
    await OrderState.choosing_branch.set()


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
    await OrderState.choosing_category.set()


# ---------- Categories ----------
@dp.message_handler(state=OrderState.choosing_category)
async def categories(message: types.Message, state: FSMContext):
    if message.text == "🥤 Drink":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Coffee", "Tea", "Milk Drink", "⬅️ Back")
        await message.answer("Choose a drink:", reply_markup=kb)
        await OrderState.choosing_item.set()

    elif message.text == "🍰 Dessert":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for d, p in DESSERTS.items():
            kb.add(f"{d} — {p}₴")
        kb.add("⬅️ Back")
        await message.answer("Choose a dessert:", reply_markup=kb)
        await OrderState.choosing_item.set()

    elif message.text == "🛒 Cart":
        await open_cart(message, state)


# ---------- Item selection ----------
@dp.message_handler(state=OrderState.choosing_item)
async def pick_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await message.answer("Main menu", reply_markup=get_main_menu())
        await OrderState.choosing_category.set()
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
        await OrderState.choosing_size.set()
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
            await OrderState.confirm_add.set()


# ---------- Size ----------
@dp.message_handler(state=OrderState.choosing_size)
async def pick_size(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data["temp_name"]
    all_drinks = {**COFFEE, **TEA, **MILK_DRINK}

    if message.text not in all_drinks[name]:
        await message.answer("Choose a button 👇")
        return

    price = all_drinks[name][message.text]
    await state.update_data(temp_size=message.text, temp_price=price)

    await message.answer(
        f"{name} ({message.text}) — {price}₴\nAdd it?",
        reply_markup=yes_no_kb()
    )
    await OrderState.confirm_add.set()


# ---------- Confirmation ----------
@dp.callback_query_handler(state=OrderState.confirm_add)
async def confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == "yes":
        data = await state.get_data()
        add_to_cart(call.from_user.id, {
            "name": data["temp_name"],
            "size": data["temp_size"],
            "price": data["temp_price"]
        })
        await call.message.answer("✅ Added", reply_markup=get_main_menu())
    else:
        await call.message.answer("❌ Cancelled", reply_markup=get_main_menu())

    await call.answer()
    await OrderState.choosing_category.set()


# ---------- Cart ----------
async def show_cart(message: types.Message) -> bool:
    cart = get_cart(message.from_user.id)

    if not cart:
        await message.answer("Your cart is empty 🕸", reply_markup=get_main_menu())
        return False

    text = "🛒 Your cart:\n\n"
    for number, item in enumerate(cart, start=1):
        text += f"{number}. {item['name']} ({item['size']}) — {item['price']}₴\n"
    text += f"\n💰 Total: {cart_total(message.from_user.id)}₴"

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Pay", "➖ Remove item")
    kb.add("⬅️ Back")

    await message.answer(text, reply_markup=kb)
    return True


async def open_cart(message: types.Message, state: FSMContext):
    if await show_cart(message):
        await state.set_state(OrderState.viewing_cart.state)
    else:
        await state.set_state(OrderState.choosing_category.state)


@dp.message_handler(state=OrderState.viewing_cart)
async def cart_actions(message: types.Message, state: FSMContext):
    if message.text == "💳 Pay":
        await pay(message, state)
        return

    if message.text == "➖ Remove item":
        await start_removing_item(message, state)
        return

    if message.text == "⬅️ Back":
        await state.set_state(OrderState.choosing_category.state)
        await message.answer("Main menu", reply_markup=get_main_menu())
        return

    await message.answer("Choose Pay, Remove item, or Back using the buttons.")




# ---------- Cart item removal ----------
@dp.message_handler(text="➖ Remove item", state="*")
async def start_removing_item(message: types.Message, state: FSMContext):
    if not get_cart(message.from_user.id):
        await message.answer("Your cart is empty 🕸")
        return

    await message.answer("Enter the item number to remove:")
    await OrderState.choosing_item_to_remove.set()


@dp.message_handler(state=OrderState.choosing_item_to_remove)
async def remove_item(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await OrderState.viewing_cart.set()
        await show_cart(message)
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

    await message.answer(
        f"✅ Removed: {removed_item['name']} ({removed_item['size']})"
    )
    await OrderState.viewing_cart.set()
    await show_cart(message)


# ---------- Payment ----------
@dp.message_handler(text="💳 Pay", state="*")
async def pay(message: types.Message, state: FSMContext):
    if await reject_blocked_customer(message):
        return

    if not get_cart(message.from_user.id):
        await message.answer("Your cart is empty 🕸")
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Online Payment (test)", "💵 Pay on Arrival")
    kb.add("⬅️ Back")
    await message.answer("Choose a payment method:", reply_markup=kb)
    await OrderState.choosing_payment.set()


@dp.message_handler(state=OrderState.choosing_payment)
async def choose_payment_method(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await message.answer("Main menu", reply_markup=get_main_menu())
        await OrderState.choosing_category.set()
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
    await OrderState.choosing_time.set()
    await message.answer("How many minutes until you arrive?", reply_markup=kb)


# ---------- Arrival time ----------
@dp.message_handler(state=OrderState.choosing_time)
async def time_handler(message: types.Message, state: FSMContext):
    try:
        minutes = int(message.text.split()[0])
    except:
        await message.answer("Choose a button")
        return

    arrival = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    cart = get_cart(message.from_user.id)
    data = await state.get_data()
    payment_method = data.get("payment_method")
    branch = data.get("branch")

    if not payment_method or not cart or branch not in BRANCHES:
        await state.finish()
        await message.answer("Your checkout session expired. Please create the order again.", reply_markup=get_main_menu())
        return

    if await reject_blocked_customer(message):
        await state.finish()
        clear_cart(message.from_user.id)
        return

    order = "\n".join([f"- {i['name']} ({i['size']})" for i in cart])
    total = cart_total(message.from_user.id)
    order_id = storage.create_order(
        user_id=message.from_user.id,
        items=cart,
        total=total,
        payment_method=payment_method,
        arrival_time=arrival,
        branch=branch,
    )
    payment_label = "Online Payment (test)" if payment_method == PAYMENT_ONLINE else "Pay on Arrival"
    msg = (
        f"🔔 NEW ORDER #{order_id}\n"
        f"👤 Customer ID: {message.from_user.id}\n"
        f"📍 Coffee shop: {branch}\n"
        f"💳 Payment: {payment_label}\n"
        f"⏰ Arrival: {arrival}\n\n{order}\n\n💰 Total: {total}₴"
    )

    for staff in STAFF_IDS:
        reply_markup = order_status_kb(order_id) if payment_method == PAYMENT_ON_ARRIVAL else None
        await bot.send_message(staff, msg, reply_markup=reply_markup)

    clear_cart(message.from_user.id)
    await state.finish()
    await message.answer(
        f"✅ We will be waiting for you at {arrival}\n📍 {branch}",
        reply_markup=get_main_menu(),
    )


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
        await call.message.edit_reply_markup()
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
            await bot.send_message(customer_id, customer_message)

        await call.message.edit_reply_markup()
        await call.answer(f"No-show recorded. Warning {warning_count}/2.")
        return

    await call.answer("Invalid order action.", show_alert=True)


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


# ---------- Back ----------
@dp.message_handler(text="⬅️ Back", state="*")
async def back(message: types.Message, state: FSMContext):
    await OrderState.choosing_category.set()
    await message.answer("Main menu", reply_markup=get_main_menu())


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
