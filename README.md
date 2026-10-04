# Wood Coffee

A Polish-language Telegram bot for placing pre-orders at **Wood Coffee** locations in Warsaw. Customers can choose drinks or desserts priced in PLN, add items to a cart, select an arrival time, and notify staff about a new order.

## Features

- Choose coffee, tea, milk drinks, and desserts.
- Select a drink size with automatic price calculation.
- Add items to a cart and calculate the total.
- Choose a Wood Coffee location by address before creating an order.
- Complete a test checkout.
- Choose online payment (test) or payment on arrival.
- Choose an arrival time of 5, 10, or 15 minutes.
- Send new-order notifications to staff in Telegram.
- Track no-show warnings for pay-on-arrival orders and block customers after two warnings.

## Technologies

- Python 3
- [aiogram 2.25.1](https://docs.aiogram.dev/en/v2.25.1/)
- [python-dotenv](https://github.com/theskumar/python-dotenv)
- SQLite (`coffee.db`)

## Installation and startup

1. Clone the repository and open its directory:

   ```bash
   git clone https://github.com/Dima1006/Wood-Coffee---project.git
   cd Wood-Coffee---project
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

   On Windows:

   ```powershell
   venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create your local configuration file from the safe template:

   ```bash
   cp .env.example .env
   ```

   Open `.env` and set:

   - `BOT_TOKEN` — the bot token obtained from [@BotFather](https://t.me/BotFather);
   - `STAFF_IDS` — a comma-separated list of Telegram IDs that should receive orders, for example `123456789,987654321`.

5. Start the bot:

   ```bash
   python bot.py
   ```

After startup, open a chat with the bot in Telegram and send the `/start` command.

## Project structure

| File | Purpose |
| --- | --- |
| `bot.py` | Command handlers, menu, and checkout flow. |
| `menu.py` | Product list, sizes, and prices. |
| `cart.py` | Temporary in-memory storage for user carts. |
| `states.py` | Conversation states for the bot. |
| `keyboards.py` | Inline keyboard for confirming an item addition. |
| `db.py` | SQLite cart-table setup. |
| `config.py` | Environment-based token and staff-ID configuration. |
| `.env.example` | Safe template for local environment variables. |

## Menu configuration

The products and prices are defined in `menu.py`. To add or update an item, edit the appropriate dictionary: `COFFEE`, `TEA`, `MILK_DRINK`, or `DESSERTS`.

## Payment and no-show policy

During checkout, customers can choose **Online Payment (test)** or **Pay on Arrival**. Only pay-on-arrival orders are eligible for no-show warnings.

## Warsaw coffee shop locations

After `/start`, customers select the location for their order:

- Wood Coffee — ul. Nowy Świat 28
- Wood Coffee — ul. Marszałkowska 84/92
- Wood Coffee — ul. Mokotowska 17

The selected location is included in the order notification sent to staff.

Staff receive an order notification in Telegram. For a pay-on-arrival order, staff can use the `✅ Arrived` or `🟨 No show` button. A no-show adds one warning to the customer. After two warnings, the customer cannot create new orders until a staff member unblocks them.

Staff can unblock a customer and reset their warnings with:

```text
/unblock <telegram_user_id>
```

Only Telegram IDs listed in `STAFF_IDS` can process order-status buttons or run the unblock command.

## Security

Never commit a real Telegram bot token. The `.env` file is ignored by Git, while `.env.example` contains only safe placeholders. If a token has ever been published, revoke it through @BotFather and create a new one before using the bot again.
