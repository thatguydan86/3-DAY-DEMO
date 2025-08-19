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

# Telegram (async)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

print("🚀 Starting RentRadar DEMO…")

# ========= Env / Config =========
WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"  # fallback
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8414219699:AAGOkFFDGEwlkxC8dsXXo0Wujt6c-ssMUVM"
).strip()

# Toggle scraper
RUN_SCRAPER = True

# Search locations and Rightmove location IDs
LOCATION_IDS: Dict[str, str] = {
    "FY1": "OUTCODE^915",   # Blackpool
    "FY2": "OUTCODE^916",
    "FY4": "OUTCODE^918",
    "PL1": "OUTCODE^2054",  # Plymouth
    "PL4": "OUTCODE^2083",
    "LL30": "OUTCODE^1464", # Llandudno
    "LL31": "OUTCODE^1465",
}

# Round robin demo areas (all included, starting with LL30)
DEMO_AREAS = ["LL30", "LL31", "FY1", "FY2", "FY4", "PL1", "PL4"]

MIN_BEDS = 1
MAX_BEDS = 4
MIN_BATHS = 0
MIN_RENT = 300
MAX_PRICE = 1300
GOOD_PROFIT_TARGET = 950
BOOKING_FEE_PCT = 0.15
DAILY_SEND_LIMIT = 5
ACTIVE_HOURS = 14

# Bills per area
BILLS_PER_AREA: Dict[str, Dict[int, int]] = {
    "FY1": {1: 420, 2: 430, 3: 460},
    "FY2": {1: 420, 2: 430, 3: 460},
    "FY4": {1: 420, 2: 440, 3: 470},
    "PL1": {1: 420, 2: 440},
    "PL4": {1: 420, 2: 440},
    "LL30": {3: 470, 4: 495},
    "LL31": {3: 470, 4: 495},
}

# ADR nightly rates
NIGHTLY_RATES: Dict[str, Dict[int, float]] = {
    "FY1": {1: 85, 2: 125, 3: 145},
    "FY2": {1: 86, 2: 126, 3: 146},
    "FY4": {1: 87, 2: 128, 3: 150},
    "PL1": {1: 95, 2: 130},
    "PL4": {1: 96, 2: 120},
    "LL30": {3: 167, 4: 272},
    "LL31": {3: 168, 4: 273},
}

# Occupancy
OCCUPANCY: Dict[str, Dict[int, float]] = {
    "FY1": {1: 0.65, 2: 0.50, 3: 0.51},
    "FY2": {1: 0.66, 2: 0.50, 3: 0.51},
    "FY4": {1: 0.64, 2: 0.52, 3: 0.53},
    "PL1": {1: 0.67, 2: 0.68},
    "PL4": {1: 0.64, 2: 0.65},
    "LL30": {3: 0.63, 4: 0.61},
    "LL31": {3: 0.63, 4: 0.61},
}

HMO_KEYWORDS = [
    "hmo", "flat share", "house share", "room to rent",
    "room in", "room only", "shared accommodation", "lodger",
    "single room", "double room", "student accommodation"
]

print("✅ Config loaded")

# ========= Logging =========
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
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
        "minBedrooms": 1,
        "maxBedrooms": 4,
        "minBathrooms": 0,
        "minPrice": 300,
        "maxPrice": 1300,
        "_includeLetAgreed": "on",
    }
    url = "https://www.rightmove.co.uk/api/_search"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"⚠️ API request failed: {resp.status_code} for {location_id}")
            return []
        return resp.json().get("properties", [])
    except Exception as e:
        print(f"⚠️ Exception fetching properties: {e}")
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

            score10 = round(max(0, min(10, (p70 / GOOD_PROFIT_TARGET) * 10)), 1)
            rag = "🟢" if p70 >= GOOD_PROFIT_TARGET else ("🟡" if p70 >= GOOD_PROFIT_TARGET * 0.7 else "🔴")

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
                "target_profit_70": p["target_profit_70"],
                "score10": f"{score10}/10",
                "rag": rag,
                "url": f"https://www.rightmove.co.uk{property_url_part}",
            }
            results.append(listing)

        except Exception:
            continue
    return results

# ========= Scraper loop =========
async def scraper_task() -> None:
    print("🚀 Scraper started in DEMO round-robin mode!")
    seen_ids: Set[str] = set()
    sent_today = 0
    last_reset_day = time.strftime("%Y-%m-%d")
    current_index = 0

    while True:
        try:
            current_day = time.strftime("%Y-%m-%d")
            if current_day != last_reset_day:
                sent_today = 0
                last_reset_day = current_day
                print(f"\n🔄 Daily send counter reset for {current_day}")

            # pick next area in round robin
            area = DEMO_AREAS[current_index]
            loc_id = LOCATION_IDS[area]
            current_index = (current_index + 1) % len(DEMO_AREAS)

            print(f"\n📍 DEMO scrape: {area}")
            raw_props = fetch_properties(loc_id)
            filtered = filter_properties(raw_props, area, seen_ids)

            if filtered:
                for listing in filtered[:1]:  # only send one per cycle
                    seen_ids.add(listing["id"])
                    print(f"📤 SENT DEMO: {listing['address']} – £{listing['rent_pcm']}")
                    post_json(WEBHOOK_URL, listing)
                    sent_today += 1
            else:
                print(f"❌ No new leads in {area}, skipping…")

            await asyncio.sleep(3600)

        except Exception as e:
            print(f"🔥 Error: {e}")
            await asyncio.sleep(300)

# ========= Telegram welcome =========
def welcome_text() -> str:
    return (
        "👋 <b>Welcome to RentRadar — 3-Day Demo</b>\n\n"
        "Here’s what to expect:\n"
        "• We scan Rightmove 24/7 for your criteria\n"
        "• We estimate SA profit at 50% / 70% / 100%\n"
        "• We’ll send demo leads here so you can see it in action\n\n"
        "<i>Note: Demo leads are shared with all trial users. Paid members get "
        "exclusive alerts for their own area & criteria.</i> 🚀"
    )

def build_start_payload(update: Update, start_param: Optional[str]) -> dict:
    user = update.effective_user
    chat = update.effective_chat
    return {
        "event": "start",
        "source": "telegram_bot",
        "ts": int(time.time()),
        "start_param": start_param or "",
        "telegram": {
            "user_id": user.id if user else None,
            "username": getattr(user, "username", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
            "language_code": getattr(user, "language_code", None),
        },
        "chat": {
            "id": chat.id if chat else None,
            "type": getattr(chat, "type", None),
            "title": getattr(chat, "title", None),
        },
    }

async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start_param = context.args[0] if context.args else None
    payload = build_start_payload(update, start_param)
    post_json(WEBHOOK_URL, payload)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 What I’ll receive", callback_data="what_receive")],
        [InlineKeyboardButton("⚡ Upgrade to Exclusive Alerts", url="https://rent-radar.co.uk")],
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
    data = (query.data or "").strip()
    if data == "what_receive":
        await query.answer()
        await query.message.reply_text(
            "You’ll receive demo Rent-to-SA leads with:\n"
            "• Rent, bills & fees\n"
            "• ADR + occupancy\n"
            "• Profit at 50% / 70% / 100%\n"
            "• Direct link to the listing"
        )
    else:
        await query.answer()

async def telegram_bot_task() -> None:
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set; Telegram bot will NOT run.")
        while True:
            await asyncio.sleep(3600)
    else:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", tg_start))
        app.add_handler(CommandHandler("help", tg_help))
        app.add_handler(CallbackQueryHandler(tg_callback))
        log.info("🤖 Telegram bot starting (polling)…")
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.start()
        try:
            await asyncio.Event().wait()
        finally:
            await app.stop()
            await app.shutdown()

# ========= Keepalive HTTP Server =========
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
