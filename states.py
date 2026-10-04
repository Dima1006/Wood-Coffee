from aiogram.dispatcher.filters.state import State, StatesGroup

class OrderState(StatesGroup):
    choosing_branch = State()
    choosing_category = State()
    choosing_item = State()
    choosing_size = State()
    confirm_add = State()
    viewing_cart = State()
    choosing_payment = State()
    choosing_time = State()
    choosing_item_to_remove = State()
