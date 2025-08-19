import os
import asyncio
import time
import random
import requests
import logging
from typing import Dict, List, Set, Optional

# Keepalive web server for Railway (no extra deps)
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
    "xxx"
).strip()

RUN_SCRAPER = True

# Search locations and Rightmove location IDs
LOCATION_IDS: Dict[str, str] = {
    "FY1": "OUTCODE^915",   # Blackpool
    "FY2": "OUTCODE^916",
    "PL1": "OUTCODE^2054",  # Plymouth
    "PL4": "OUTCODE^2083",
    "LL30": "OUTCODE^1464", # Llandudno
    "LL31": "OUTCODE^1465",
    "FY4": "OUTCODE^918"
}

# Round robin demo areas
DEMO_AREAS = ["FY1", "FY2", "FY4", "PL1", "PL4", "LL30", "LL31"]

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
    "FY2": {1: 420, 2: 430, 3: 460},
    "FY4": {1: 420, 2: 440, 3: 470},
    "PL1": {1: 420, 2: 440},
    "PL4": {1: 420, 2: 440},
    "LL30": {3: 470, 4: 495},
    "LL31": {3: 470, 4: 495},
}

# ADR (nightly rates) per area
NIGHTLY_RATES: Dict[str, Dict[int, float]] = {
    "FY1": {1: 85, 2: 125, 3: 145},
    "FY2": {1: 86, 2: 126, 3: 146},
    "FY4": {1: 87, 2: 128, 3: 150},
    "PL1": {1: 95, 2: 130},
    "PL4": {1: 96, 2: 120},
    "LL30": {3: 167, 4: 272},
    "LL31": {3: 168, 4: 273},
}

# Occupancy per area
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
        "occ_rate": int(round(occ_rate * 100)),  # % format
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

            # ✅ Skip incomplete listings
            if not prop_id or not address or not beds or not rent:
                print(f"🚫 Skipped incomplete listing (missing data) – {prop_id}")
                continue

            if prop_id in seen_ids:
                print(f"⏩ SKIPPED DUPLICATE: {address}")
                continue

            if is_hmo_or_room(prop):
                print(f"🚫 SKIPPED HMO/ROOM: {address}")
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

        except Exception as e:
            print(f"⚠️ Error filtering property: {e}")
            continue
    return results
