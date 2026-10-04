import os

from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

STAFF_IDS = [
    int(staff_id.strip())
    for staff_id in os.getenv("STAFF_IDS", "").split(",")
    if staff_id.strip()
]

BRANCHES = (
    "Wood Coffee — ul. Nowy Świat 28",
    "Wood Coffee — ul. Marszałkowska 84/92",
    "Wood Coffee — ul. Mokotowska 17",
)
