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

MIN_BEDS = 1
MAX_BEDS = 4
MIN_RENT = 500
MAX_PRICE = 1500
GOOD_PROFIT_TARGET = 1200
BOOKING_FEE_PCT = 0.15

# Bills per area (monthly)
BILLS_TABLE = {
    ("FY1", 2): 395,
    ("FY1", 3): 395,
    ("FY2", 2): 395,
    ("FY2", 3): 395,
    ("PL1", 1): 420,
    ("PL1", 2): 420,
    ("PL4", 1): 420,
    ("PL4", 2): 420,
    ("LL30", 3): 380,
    ("LL30", 4): 380,
    ("LL31", 3): 380,
    ("LL31", 4): 380,
}

# ADR table
ADR_TABLE = {
    ("FY1", 2): 125, ("FY1", 3): 145,
    ("FY2", 2): 125, ("FY2", 3): 145,
    ("PL1", 1): 95,  ("PL1", 2): 130,
    ("PL4", 1): 96,  ("PL4", 2): 120,
    ("LL30", 3): 167, ("LL30", 4): 272,
    ("LL31", 3): 167, ("LL31", 4): 272,
}

# Average occupancy %
OCC_TABLE = {
    ("FY1", 2): 50, ("FY1", 3): 51,
    ("FY2", 2): 50, ("FY2", 3): 51,
    ("PL1", 1): 67, ("PL1", 2): 68,
    ("PL4", 1): 64, ("PL4", 2): 65,
    ("LL30", 3): 63, ("LL30", 4): 61,
    ("LL31", 3): 63, ("LL31", 4): 61,
}

# ========= Helpers =========
def monthly_net_from_adr(adr: float, occ_percent: float) -> float:
    gross = adr * (occ_percent / 100) * 30
    return gross * (1 - BOOKING_FEE_PCT)

def calculate_profits(rent_pcm: int, area: str, beds: int):
    nightly_rate = ADR_TABLE.get((area, beds), 100)
    avg_occ = OCC_TABLE.get((area, beds), 60)
    total_bills = BILLS_TABLE.get((area, beds), 400)

    def profit(occ_percent: float) -> int:
        net_income = monthly_net_from_adr(nightly_rate, occ_percent)
        return int(round(net_income - rent_pcm - total_bills))

    return {
        "night_rate": nightly_rate,
        "avg_occ": avg_occ,
        "total_bills": total_bills,
        "profit_50": profit(50),
        "profit_70": profit(70),
        "profit_100": profit(100),
    }

def format_message(listing: Dict):
    tick = "✅" if listing["profit_70"] >= GOOD_PROFIT_TARGET else ""
    return f"""📢 New Rent-to-SA Lead 🔵
Score: {listing['score10']}/10

📍 {listing['address']} — {listing['area']}
🏡 {listing['bedrooms']}-bed {listing['propertySubType']} | 🛁 {listing['bathrooms']} baths
💰 Rent: £{listing['rent_pcm']}/mo | 📊 Bills: £{listing['bills']}/mo | 📄 Fees: {int(BOOKING_FEE_PCT*100)}%

💵 Profit (ADR £{listing['night_rate']} / Avg Occ: {listing['avg_occ']}%)
• 50% → £{listing['profit_50']}
• 70% → £{listing['profit_70']} {tick} Target £{GOOD_PROFIT_TARGET}
• 100% → £{listing['profit_100']}

🔗 View listing: {listing['url']}

📌 Estimate figures drawn from Booking.com, AirBnB & Property Market Intel.
We advise you do your own due diligence.

💡 Want exclusive property leads tailored to you?
We can set up your own personal feed with your exact criteria, target area, and private deals — starting from £29/month.
Sign up at rent-radar.co.uk or email support@rent-radar.co.uk
"""

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
def filter_properties(properties: List[Dict], area: str) -> List[Dict]:
    results = []
    for prop in properties:
        try:
            beds = prop.get("bedrooms")
            rent = prop.get("price", {}).get("amount")
            baths = prop.get("bathrooms") or 0
            subtype = (prop.get("propertySubType") or "House").title()
            address = prop.get("displayAddress", "Unknown")

            if not beds or not rent:
                continue
            if rent < MIN_RENT or rent > MAX_PRICE:
                continue

            p = calculate_profits(rent, area, beds)
            p70 = p["profit_70"]

            score10 = round(max(0, min(10, (p70 / GOOD_PROFIT_TARGET) * 10)), 1)
            listing = {
                "id": prop.get("id"),
                "area": area,
                "address": address,
                "rent_pcm": rent,
                "bedrooms": beds,
                "bathrooms": baths,
                "propertySubType": subtype,
                "url": f"https://www.rightmove.co.uk{prop.get('propertyUrl')}",
                "night_rate": p["night_rate"],
                "avg_occ": p["avg_occ"],
                "bills": p["total_bills"],
                "profit_50": p["profit_50"],
                "profit_70": p70,
                "profit_100": p["profit_100"],
                "score10": score10
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
        try:
            print(f"\n⏰ New scrape at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            new_listings = await scrape_once(seen_ids)

            if not new_listings:
                print("ℹ️ No new listings this run.")

            for listing in new_listings:
                msg = format_message(listing)
                try:
                    requests.post(WEBHOOK_URL, json={"text": msg}, timeout=10)
                except Exception as e:
                    print(f"⚠️ Failed to POST to webhook: {e}")

            sleep_duration = 3600 + random.randint(-300, 300)
            print(f"💤 Sleeping {sleep_duration} seconds…")
            await asyncio.sleep(sleep_duration)

        except Exception as e:
            print(f"🔥 Error: {e}")
            await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
