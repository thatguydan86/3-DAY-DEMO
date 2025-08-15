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

# Bedrooms
MIN_BEDS = 1
MAX_BEDS = 4
MIN_BATHS = 0
MIN_RENT = 300
MAX_PRICE = 1200
GOOD_PROFIT_TARGET = 1200
BOOKING_FEE_PCT = 0.15
DAILY_SEND_LIMIT = 2  # Max leads sent per day in demo mode

# Bills per area (Council tax + utilities + broadband + TV licence)
BILLS_PER_AREA: Dict[str, int] = {
    "FY1": 587,
    "FY2": 612,
    "PL1": 598,
    "PL4": 605,
    "LL30": 615,
    "LL31": 621,
}

# ADR & Occupancy defaults
NIGHTLY_RATES: Dict[str, Dict[int, float]] = {
    "FY1": {2: 125.0, 3: 145.0},
    "FY2": {2: 125.0, 3: 145.0},
    "PL1": {1: 95.0, 2: 130.0},
    "PL4": {1: 96.0, 2: 120.0},
    "LL30": {3: 167.0, 4: 272.0},
    "LL31": {3: 167.0, 4: 272.0},
}

OCCUPANCY: Dict[str, Dict[int, float]] = {
    "FY1": {2: 0.50, 3: 0.51},
    "FY2": {2: 0.50, 3: 0.51},
    "PL1": {1: 0.67, 2: 0.68},
    "PL4": {1: 0.64, 2: 0.65},
    "LL30": {3: 0.63, 4: 0.61},
    "LL31": {3: 0.63, 4: 0.61},
}

# Keywords to skip HMOs / room lets
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
    nightly_rate = NIGHTLY_RATES.get(area, {}).get(beds, 100.0)
    occ_rate = OCCUPANCY.get(area, {}).get(beds, 0.65)
    total_bills = BILLS_PER_AREA.get(area, 600)

    def profit(occ: float) -> int:
        net_income = monthly_net_from_adr(nightly_rate, occ)
        return int(round(net_income - rent_pcm - total_bills))

    return {
        "night_rate": nightly_rate,
        "occ_rate": occ_rate,
        "total_bills": total_bills,
        "profit_50": profit(0.5),
        "profit_70": profit(0.7),
        "profit_100": profit(1.0),
    }

def is_hmo_or_room(listing: Dict) -> bool:
    text_fields = [
        listing.get("displayAddress", "").lower(),
        listing.get("summary", "").lower(),
        listing.get("propertySubType", "").lower()
    ]
    return any(keyword in text for text in text_fields for keyword in HMO_KEYWORDS)

# ========= Rightmove fetch with retries =========
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

    retries = 3
    for attempt in range(retries):
        try:
            headers = {
                "User-Agent": random.choice([
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ])
            }
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("properties", [])
            else:
                print(f"⚠️ API request failed ({resp.status_code}) for {location_id} – retry {attempt+1}/{retries}")
        except Exception as e:
            print(f"⚠️ Exception fetching properties for {location_id} – retry {attempt+1}/{retries}: {e}")
        time.sleep(3 + attempt * 2)

    print(f"❌ Giving up on {location_id} after {retries} attempts")
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
                "occ_rate": f"{round(p['occ_rate'] * 100)}%",
                "bills": p["total_bills"],
                "profit_50": p["profit_50"],
                "profit_70": p70,
                "profit_100": p["profit_100"],
                "target_profit_70": GOOD_PROFIT_TARGET,
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
            except Exception as e:
                print(f"⚠️ Failed to POST to webhook: {e}")

        await asyncio.sleep(random.uniform(1, 2))  # Small delay between areas

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
