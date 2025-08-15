import asyncio
import time
import random
import requests
from typing import Dict, List, Set

print("🚀 Starting RentRadar DEMO…")

# ========= Config =========
WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

LOCATION_IDS: Dict[str, str] = {
    "FY1": "OUTCODE^915",
    "FY2": "OUTCODE^916",
    "PL1": "OUTCODE^2054",
    "PL4": "OUTCODE^2083",
    "LL30": "OUTCODE^1464",
    "LL31": "OUTCODE^1465",
}

# Area-specific bills
BILLS_PER_AREA: Dict[str, int] = {
    "FY1": 600,
    "FY2": 600,
    "PL1": 600,
    "PL4": 600,
    "LL30": 600,
    "LL31": 600,
}

# ADR per area
NIGHTLY_RATES: Dict[str, int] = {
    "FY1": 125,
    "FY2": 125,
    "PL1": 130,
    "PL4": 120,
    "LL30": 100,
    "LL31": 100,
}

# Occupancy per area (now as whole percentages)
OCCUPANCY_RATES: Dict[str, int] = {
    "FY1": 60,
    "FY2": 60,
    "PL1": 68,
    "PL4": 65,
    "LL30": 60,
    "LL31": 60,
}

BOOKING_FEE_PCT = 0.15
GOOD_PROFIT_TARGET = 1200

# ========= Helpers =========
def monthly_net_from_adr(adr: float, occ_percent: int) -> float:
    occ = occ_percent / 100  # Convert back to decimal for calc
    gross = adr * occ * 30
    return gross * (1 - BOOKING_FEE_PCT)

def calculate_profits(rent_pcm: int, area: str):
    nightly_rate = NIGHTLY_RATES.get(area, 100)
    total_bills = BILLS_PER_AREA.get(area, 600)
    occ_percent = OCCUPANCY_RATES.get(area, 60)

    def profit(occ_percent: int) -> int:
        net_income = monthly_net_from_adr(nightly_rate, occ_percent)
        return int(round(net_income - rent_pcm - total_bills))

    return {
        "night_rate": nightly_rate,
        "occ_percent": occ_percent,
        "total_bills": total_bills,
        "profit_50": profit(50),
        "profit_70": profit(70),
        "profit_100": profit(100),
    }

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
def filter_properties(properties: List[Dict], area: str) -> List[Dict]:
    results = []
    for prop in properties:
        try:
            prop_type = (prop.get("propertySubType") or "").lower()
            if any(kw in prop_type for kw in ["hmo", "house share", "flat share", "room to rent", "shared accommodation"]):
                continue

            rent = prop.get("price", {}).get("amount")
            if not rent:
                continue

            p = calculate_profits(rent, area)
            p70 = p["profit_70"]

            score10 = round(max(0, min(10, (p70 / GOOD_PROFIT_TARGET) * 10)), 1)
            rag = "🟢" if p70 >= GOOD_PROFIT_TARGET else ("🟡" if p70 >= GOOD_PROFIT_TARGET * 0.7 else "🔴")

            listing = {
                "id": prop.get("id"),
                "area": area,
                "address": prop.get("displayAddress", "Unknown"),
                "rent_pcm": rent,
                "night_rate": p["night_rate"],
                "occ_percent": p["occ_percent"],  # already a whole number now
                "bills": p["total_bills"],
                "profit_50": p["profit_50"],
                "profit_70": p["profit_70"],
                "profit_100": p["profit_100"],
                "target_profit_70": GOOD_PROFIT_TARGET,
                "score10": score10,
                "rag": rag,
                "url": f"https://www.rightmove.co.uk{prop.get('propertyUrl')}",
            }
            results.append(listing)
        except Exception:
            continue
    return results

# ========= Scraper loop =========
async def scrape_once(seen_ids: Set[str]) -> List[Dict]:
    new_listings = []
    for area, loc_id in LOCATION_IDS.items():
        print(f"\n📍 Searching {area}…")
        raw_props = fetch_properties(loc_id)
        filtered = filter_properties(raw_props, area)
        for listing in filtered:
            if listing["id"] in seen_ids:
                continue
            seen_ids.add(listing["id"])
            new_listings.append(listing)
    return new_listings

async def main() -> None:
    print("🚀 Scraper started in DEMO mode!")
    seen_ids: Set[str] = set()
    while True:
        print(f"\n⏰ New scrape at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        new_listings = await scrape_once(seen_ids)

        if not new_listings:
            print("ℹ️ No new listings this run.")

        for listing in new_listings:
            print(f"✅ Sending: {listing['address']} – £{listing['rent_pcm']} – ADR £{listing['night_rate']} – Occ {listing['occ_percent']}%")
            try:
                requests.post(WEBHOOK_URL, json=listing, timeout=10)
            except Exception as e:
                print(f"⚠️ Failed to POST to webhook: {e}")

        sleep_duration = 3600 + random.randint(-300, 300)
        print(f"💤 Sleeping {sleep_duration} seconds…")
        await asyncio.sleep(sleep_duration)

if __name__ == "__main__":
    asyncio.run(main())
