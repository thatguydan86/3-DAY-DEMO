import asyncio
import time
import random
import requests
from typing import Dict, List, Set

print("🚀 Starting RentRadar DEMO…")

# ========= Config =========
WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

# Search locations and Rightmove location IDs
LOCATION_IDS: Dict[str, str] = {
    "FY1": "OUTCODE^915",
    "FY2": "OUTCODE^916",
    "PL1": "OUTCODE^2054",
    "PL4": "OUTCODE^2083",
    "LL30": "OUTCODE^1464",
    "LL31": "OUTCODE^1465",
}

MIN_BEDS = 1
MAX_BEDS = 4
MIN_BATHS = 0
MIN_RENT = 300
MAX_PRICE = 1300
GOOD_PROFIT_TARGET = 950  # used for scoring AND Telegram target
BOOKING_FEE_PCT = 0.15
DAILY_SEND_LIMIT = 5
ACTIVE_HOURS = 14  # spread sends across 14 hours

# Bills per area & bedroom count
BILLS_PER_AREA: Dict[str, Dict[int, int]] = {
    "FY1": {2: 587, 3: 645},
    "FY2": {2: 590, 3: 648},
    "PL1": {1: 512, 2: 590},
    "PL4": {1: 500, 2: 575},
    "LL30": {3: 620, 4: 690},
    "LL31": {3: 625, 4: 695},
}

# ADR & Occupancy defaults
NIGHTLY_RATES: Dict[str, Dict[int, float]] = {
    "FY1": {2: 125, 3: 145},
    "FY2": {2: 126, 3: 146},
    "PL1": {1: 95, 2: 130},
    "PL4": {1: 96, 2: 120},
    "LL30": {3: 167, 4: 272},
    "LL31": {3: 168, 4: 273},
}

OCCUPANCY: Dict[str, Dict[int, float]] = {
    "FY1": {2: 0.50, 3: 0.51},
    "FY2": {2: 0.50, 3: 0.51},
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

# ========= Helpers =========
def monthly_net_from_adr(adr: float, occ: float) -> float:
    gross = adr * occ * 30
    return gross * (1 - BOOKING_FEE_PCT)

def calculate_profits(rent_pcm: int, area: str, beds: int):
    nightly_rate = NIGHTLY_RATES.get(area, {}).get(beds, 100)
    occ_rate = OCCUPANCY.get(area, {}).get(beds, 0.65)
    total_bills = BILLS_PER_AREA.get(area, {}).get(beds, 600)

    def profit(occ: float) -> int:
        net_income = monthly_net_from_adr(nightly_rate, occ)
        return int(round(net_income - rent_pcm - total_bills))

    return {
        "night_rate": nightly_rate,
        "occ_rate": int(round(occ_rate * 100)),  # % format for Telegram
        "total_bills": total_bills,
        "profit_50": profit(0.5),
        "profit_70": profit(0.7),
        "profit_100": profit(1.0),
        "target_profit_70": GOOD_PROFIT_TARGET  # now matches config
    }

def is_hmo_or_room(listing: Dict) -> bool:
    text_fields = [
        listing.get("displayAddress", "").lower(),
        listing.get("summary", "").lower(),
        listing.get("propertySubType", "").lower()
    ]
    return any(keyword in text for text in text_fields for keyword in HMO_KEYWORDS)

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
    try:
        resp = requests.get(url, params=params, timeout=30)
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
            rent = prop.get("price", {}).get("amount")

            if not beds or not rent:
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

            listing = {
                "id": prop_id,
                "area": area,
                "address": address,
                "rent_pcm": rent,
                "bedrooms": beds,
                "night_rate": p["night_rate"],
                "occ_rate": p["occ_rate"],
                "bills": p["total_bills"],
                "profit_50": p["profit_50"],
                "profit_70": p70,
                "profit_100": p["profit_100"],
                "target_profit_70": p["target_profit_70"],
                "score10": score10,
                "rag": rag,
                "url": f"https://www.rightmove.co.uk{prop.get('propertyUrl')}",
            }
            results.append(listing)

        except Exception as e:
            print(f"⚠️ Error filtering property: {e}")
            continue
    return results

# ========= Scraper loop =========
async def scrape_once(seen_ids: Set[str], sent_today: int) -> int:
    new_sent_count = sent_today
    send_interval = (ACTIVE_HOURS * 3600) // DAILY_SEND_LIMIT

    for area, loc_id in LOCATION_IDS.items():
        print(f"\n📍 Searching {area}…")
        raw_props = fetch_properties(loc_id)
        filtered = filter_properties(raw_props, area, seen_ids)

        if not filtered:
            print(f"❌ NO PROPERTIES FOUND for {area}")
            continue

        for listing in filtered:
            if new_sent_count >= DAILY_SEND_LIMIT:
                return new_sent_count

            seen_ids.add(listing["id"])
            print(f"📤 SENT PROPERTY: {listing['address']} – £{listing['rent_pcm']} – {listing['bedrooms']} beds")
            try:
                requests.post(WEBHOOK_URL, json=listing, timeout=10)
                new_sent_count += 1
                await asyncio.sleep(send_interval)  # spread sends out
            except Exception as e:
                print(f"⚠️ Failed to POST to webhook: {e}")
    return new_sent_count

async def main() -> None:
    print("🚀 Scraper started in DEMO mode!")
    seen_ids: Set[str] = set()
    sent_today = 0
    last_reset_day = time.strftime("%Y-%m-%d")

    while True:
        try:
            current_day = time.strftime("%Y-%m-%d")
            if current_day != last_reset_day:
                sent_today = 0
                last_reset_day = current_day
                print(f"\n🔄 Daily send counter reset for {current_day}")

            print(f"\n⏰ New scrape at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            sent_today = await scrape_once(seen_ids, sent_today)

            sleep_duration = 3600 + random.randint(-300, 300)
            print(f"💤 Sleeping {sleep_duration} seconds…")
            await asyncio.sleep(sleep_duration)

        except Exception as e:
            print(f"🔥 Error: {e}")
            await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
