import os
import asyncio
import time
import random
import requests
import logging
from typing import Dict, List, Set, Optional

# Keepalive web server for Railway
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

print("🚀 Starting RentRadar DEMO…")

# ========= Env / Config =========
WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8414219699:AAGOkFFDGEwlkxC8dsXXo0Wujt6c-ssMUVM"
).strip()

RUN_SCRAPER = True

# Demo areas only (round-robin rotation)
DEMO_LOCATIONS: Dict[str, str] = {
    "FY1": "OUTCODE^915",  # Blackpool
    "PL1": "OUTCODE^2054", # Plymouth
    "LL30": "OUTCODE^1464" # Llandudno
}
DEMO_AREAS = list(DEMO_LOCATIONS.items())  # ordered for cycling
area_index = 0  # global pointer

MIN_BEDS = 1
MAX_BEDS = 4
MIN_BATHS = 0
MIN_RENT = 300
MAX_PRICE = 1300
GOOD_PROFIT_TARGET = 950
BOOKING_FEE_PCT = 0.15
DAILY_SEND_LIMIT = 5
ACTIVE_HOURS = 14

# Bills per area & bedroom count
BILLS_PER_AREA: Dict[str, Dict[int, int]] = {
    "FY1": {1: 420, 2: 430, 3: 460},
    "PL1": {1: 420, 2: 440},
    "LL30": {3: 470, 4: 495},
}

# ADR (nightly rates) per area
NIGHTLY_RATES: Dict[str, Dict[int, float]] = {
    "FY1": {1: 85, 2: 125, 3: 145},
    "PL1": {1: 95, 2: 130},
    "LL30": {3: 167, 4: 272},
}

# Occupancy per area
OCCUPANCY: Dict[str, Dict[int, float]] = {
    "FY1": {1: 0.65, 2: 0.50, 3: 0.51},
    "PL1": {1: 0.67, 2: 0.68},
    "LL30": {3: 0.63, 4: 0.61},
}

HMO_KEYWORDS = [
    "hmo", "flat share", "house share", "room to rent",
    "room in", "room only", "shared accommodation", "lodger",
    "single room", "double room", "student accommodation"
]

print("✅ Config loaded")

# ========= Logging =========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("rentradar")

# ========= Helpers =========
def monthly_net_from_adr(adr: float, occ: float) -> float:
    gross = adr * occ * 30
    return gross * (1 - BOOKING_FEE_PCT)

def calculate_profits(rent_pcm: int, area: str, beds: int):
    nightly_rate = NIGHTLY_RATES.get(area, {}).get(beds, 100)
    occ_rate = OCCUPANCY.get(area, {}).get(beds, 0.65)
    total_bills = BILLS_PER_AREA.get(area, {}).get(beds, 420)

    def profit(occ: float) -> int:
        net_income = monthly_net_from_adr(nightly_rate, occ)
        return int(round(net_income - rent_pcm - total_bills))

    return {
        "night_rate": nightly_rate,
        "occ_rate": int(round(occ_rate * 100)),
        "total_bills": total_bills,
        "profit_50": profit(0.5),
        "profit_70": profit(0.7),
        "profit_100": profit(1.0),
        "target_profit_70": GOOD_PROFIT_TARGET
    }

def is_hmo_or_room(listing: Dict) -> bool:
    text_fields = [
        listing.get("displayAddress", "").lower(),
        listing.get("summary", "").lower(),
        listing.get("propertySubType", "").lower()
    ]
    return any(keyword in text for text in text_fields for keyword in HMO_KEYWORDS)

def post_json(url: str, payload: dict, retries: int = 3, timeout: int = 12) -> bool:
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if 200 <= r.status_code < 300:
                return True
            log.warning("Webhook non-2xx (attempt %d): %s %s", attempt, r.status_code, r.text[:200])
        except requests.RequestException as e:
            log.warning("Webhook error (attempt %d): %s", attempt, e)
        time.sleep(0.8 * attempt)
    return False

# ========= Rightmove fetch =========
def fetch_properties(location_id: str) -> List[Dict]:
    params = {
        "locationIdentifier": location_id,
        "numberOfPropertiesPerPage": 24,
        "radius": 0.0,
        "index": 0,
        "channel": "RENT",
        "currencyCode": "GBP",
        "sortType": 6,
        "viewType": "LIST",
        "minBedrooms": MIN_BEDS,
        "maxBedrooms": MAX_BEDS,
        "minBathrooms": MIN_BATHS,
        "minPrice": MIN_RENT,
        "maxPrice": MAX_PRICE,
        "_includeLetAgreed": "on",
    }
    url = "https://www.rightmove.co.uk/api/_search"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            return []
        return resp.json().get("properties", [])
    except Exception:
        return []

# ========= Filter =========
def filter_properties(properties: List[Dict], area: str, seen_ids: Set[str]) -> List[Dict]:
    results = []
    for prop in properties:
        try:
            prop_id = prop.get("id")
            address = prop.get("displayAddress", "Unknown")
            beds = prop.get("bedrooms")
            baths = prop.get("bathrooms", 1)
            rent = prop.get("price", {}).get("amount")

            if not beds or not rent:
                continue
            if prop_id in seen_ids:
                continue
            if is_hmo_or_room(prop):
                continue

            p = calculate_profits(rent, area, beds)
            p70 = p["profit_70"]

            property_url_part = prop.get("propertyUrl") or f"/properties/{prop_id}"
            listing = {
                "id": prop_id,
                "area": area,
                "address": address,
                "rent_pcm": rent,
                "bedrooms": beds,
                "bathrooms": baths,
                "night_rate": p["night_rate"],
                "occ_rate": p["occ_rate"],
                "bills": p["total_bills"],
                "profit_50": p["profit_50"],
                "profit_70": p70,
                "profit_100": p["profit_100"],
                "url": f"https://www.rightmove.co.uk{property_url_part}",
            }
            results.append(listing)

        except Exception:
            continue
    return results

# ========= Scraper loop (round-robin) =========
async def scrape_once(seen_ids: Set[str], sent_today: int) -> int:
    global area_index
    new_sent_count = sent_today
    send_interval = max(1, (ACTIVE_HOURS * 3600) // max(1, DAILY_SEND_LIMIT))

    # pick next area in rotation
    area, loc_id = DEMO_AREAS[area_index]
    area_index = (area_index + 1) % len(DEMO_AREAS)

    print(f"\n📍 Searching {area}…")
    raw_props = fetch_properties(loc_id)
    filtered = filter_properties(raw_props, area, seen_ids)

    if not filtered:
        return new_sent_count

    for listing in filtered:
        if new_sent_count >= DAILY_SEND_LIMIT:
            return new_sent_count

        seen_ids.add(listing["id"])
        print(f"📤 SENT PROPERTY: {listing['address']} – £{listing['rent_pcm']}")
        try:
            post_json(WEBHOOK_URL, listing)
            new_sent_count += 1
            await asyncio.sleep(send_interval)
        except Exception as e:
            print(f"⚠️ Failed to POST: {e}")

    return new_sent_count

async def scraper_task() -> None:
    seen_ids: Set[str] = set()
    sent_today = 0
    last_reset_day = time.strftime("%Y-%m-%d")

    while True:
        try:
            current_day = time.strftime("%Y-%m-%d")
            if current_day != last_reset_day:
                sent_today = 0
                last_reset_day = current_day
                print(f"\n🔄 Reset counter {current_day}")

            sent_today = await scrape_once(seen_ids, sent_today)
            sleep_duration = 3600 + random.randint(-300, 300)
            await asyncio.sleep(sleep_duration)

        except Exception as e:
            print(f"🔥 Error: {e}")
            await asyncio.sleep(300)

# ========= Telegram =========
def welcome_text() -> str:
    return (
        "👋 <b>Welcome to RentRadar — 3-Day Demo</b>\n\n"
        "• Demo leads rotate between Blackpool, Llandudno & Plymouth\n"
        "• Profit breakdown at 50% / 70% / 100%\n"
        "• Exclusive alerts unlocked with upgrade 🚀"
    )

async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 What I’ll receive", callback_data="what_receive")],
        [InlineKeyboardButton("⚡ Upgrade", url="https://rent-radar.co.uk")],
    ])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=welcome_text(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=kb,
    )

async def tg_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Commands:\n/start – connect\n/help – this help")

async def tg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if query.data == "what_receive":
        await query.answer()
        await query.message.reply_text("You’ll receive demo leads from Blackpool, Llandudno & Plymouth.")

async def telegram_bot_task() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", tg_start))
    app.add_handler(CommandHandler("help", tg_help))
    app.add_handler(CallbackQueryHandler(tg_callback))

    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        await app.shutdown()

# ========= Keepalive =========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_http_server():
    port = int(os.getenv("PORT", "8080"))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ========= Entry =========
async def main() -> None:
    if RUN_SCRAPER:
        await asyncio.gather(scraper_task(), telegram_bot_task())
    else:
        await telegram_bot_task()

if __name__ == "__main__":
    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.run(main())
