import asyncio
import time
import random
import requests
from typing import Dict, List, Set

print("🚀 Starting RentRadar Demo…")

# ===== Config =====
WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"
GOOD_PROFIT_TARGET = 1200
BOOKING_FEE_PCT = 0.15

AREAS = {
    "Blackpool": {
        "location_ids": ["OUTCODE^915", "OUTCODE^916"],  # FY1, FY2
        "bills": 395,
        "rates": {
            2: {"adr": 125, "occ": 0.50},
            3: {"adr": 145, "occ": 0.51}
        }
    },
    "Plymouth": {
        "location_ids": ["OUTCODE^2054", "OUTCODE^2083"],  # PL1, PL4
        "bills": 360,
        "rates": {
            1: {"adr": 95, "occ": 0.67},  # PL1
            2: {"adr": 130, "occ": 0.68}, # PL1
            "PL4_1": {"adr": 96, "occ": 0.64},  # PL4
            "PL4_2": {"adr": 120, "occ": 0.65}
        }
    },
    "Llandudno": {
        "location_ids": ["OUTCODE^1464", "OUTCODE^1465"],  # LL30, LL31
        "bills": 430,
        "rates": {
            3: {"adr": 167, "occ": 0.63},
            4: {"adr": 272, "occ": 0.61}
        }
    }
}

# ===== Helpers =====
def monthly_net_from_adr(adr: float, occ: float) -> float:
    return adr * occ * 30 * (1 - BOOKING_FEE_PCT)

def get_closest_rate(area: str, location_id: str, bedrooms: int):
    rates = AREAS[area]["rates"]

    # Special case for PL4
    if area == "Plymouth" and location_id == "OUTCODE^2083":
        key = f"PL4_{bedrooms}"
        if key in rates:
            return rates[key]

    if bedrooms in rates:
        return rates[bedrooms]

    # Closest match ±1 bedroom
    valid_keys = [b for b in rates.keys() if isinstance(b, int)]
    closest_beds = min(valid_keys, key=lambda x: abs(x - bedrooms))
    return rates[closest_beds]

def calculate_profits(rent_pcm: int, area: str, location_id: str, bedrooms: int):
    rate_data = get_closest_rate(area, location_id, bedrooms)
    adr = rate_data["adr"]
    bills = AREAS[area]["bills"]

    def profit(occ: float):
        return int(round(monthly_net_from_adr(adr, occ) - rent_pcm - bills))

    return {
        "adr": adr,
        "occ": rate_data["occ"],
        "bills": bills,
        "profit_50": profit(0.50),
        "profit_70": profit(0.70),
        "profit_100": profit(1.0)
    }

def format_whatsapp_message(listing: dict) -> str:
    # Score out of 10
    score10 = round(max(0, min(10, (listing['profit_70'] / GOOD_PROFIT_TARGET) * 10)), 1)
    avg_occ_pct = int(listing['occ'] * 100)
    tick = "✅" if listing["profit_70"] >= GOOD_PROFIT_TARGET else "❌"

    return (
        f"🔔 New Rent-to-SA Lead 🔵\n"
        f"Score: {score10}/10\n\n"
        f"📍 {listing['address']} — {listing['area']}\n"
        f"🏠 {listing['bedrooms']}-bed {listing.get('property_type', '')} | 🛁 {listing.get('bathrooms', 'N/A')} baths\n"
        f"💷 Rent: £{listing['rent_pcm']}/mo | 📊 Bills: £{listing['bills']}/mo | 💳 Fees: {int(BOOKING_FEE_PCT*100)}%\n\n"
        f"💰 Profit (ADR £{listing['adr']} / Avg Occ: {avg_occ_pct}%)\n"
        f"• 50% → £{listing['profit_50']}\n"
        f"• 70% → £{listing['profit_70']} {tick} Target £{GOOD_PROFIT_TARGET}\n"
        f"• 100% → £{listing['profit_100']}\n\n"
        f"🔗 View listing: {listing['url']}\n\n"
        f"⚠️ Disclaimer: This is an estimated serviced accommodation projection based on average ADR & occupancy for the area. "
        f"Figures are indicative only and should be verified before making investment decisions."
    )

def fetch_properties(location_id: str, min_beds=1, max_beds=4, min_rent=750, max_rent=1200):
    params = {
        "locationIdentifier": location_id,
        "numberOfPropertiesPerPage": 24,
        "radius": 0.0,
        "index": 0,
        "channel": "RENT",
        "currencyCode": "GBP",
        "sortType": 6,
        "_includeLetAgreed": "on",
        "minBedrooms": min_beds,
        "maxBedrooms": max_beds,
        "minPrice": min_rent,
        "maxPrice": max_rent + 100  # widened cap
    }
    try:
        r = requests.get("https://www.rightmove.co.uk/api/_search", params=params, timeout=30)
        if r.status_code != 200:
            print(f"⚠️ Failed API call {r.status_code} for {location_id}")
            return []
        return r.json().get("properties", [])
    except Exception as e:
        print(f"⚠️ Exception fetching {location_id}: {e}")
        return []

def filter_properties(properties: List[Dict], area: str, location_id: str):
    results = []
    for prop in properties:
        try:
            beds = prop.get("bedrooms")
            rent = prop.get("price", {}).get("amount")
            if not beds or not rent:
                continue

            p = calculate_profits(rent, area, location_id, beds)
            listing = {
                "id": prop.get("id"),
                "area": area,
                "address": prop.get("displayAddress", "Unknown"),
                "rent_pcm": rent,
                "bedrooms": beds,
                "bathrooms": prop.get("bathrooms") or "N/A",
                "property_type": prop.get("propertySubType", "").title(),
                "adr": p["adr"],
                "occ": p["occ"],
                "bills": p["bills"],
                "profit_50": p["profit_50"],
                "profit_70": p["profit_70"],
                "profit_100": p["profit_100"],
                "url": f"https://www.rightmove.co.uk{prop.get('propertyUrl')}"
            }
            results.append(listing)
        except Exception:
            continue
    return results

async def scrape_once(seen_ids: Set[str]):
    new_listings = []
    for area, cfg in AREAS.items():
        for loc_id in cfg["location_ids"]:
            print(f"📍 Searching {area} ({loc_id})…")
            raw = fetch_properties(loc_id)
            filtered = filter_properties(raw, area, loc_id)
            for listing in filtered:
                if listing["id"] in seen_ids:
                    continue
                seen_ids.add(listing["id"])
                new_listings.append(listing)
    return new_listings

async def main():
    print("🚀 Scraper started!")
    seen_ids: Set[str] = set()
    while True:
        try:
            print(f"\n⏰ Scrape at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            new_listings = await scrape_once(seen_ids)
            if not new_listings:
                print("ℹ️ No new listings this run.")

            for listing in new_listings:
                message = format_whatsapp_message(listing)
                print(f"✅ Sending: {listing['address']} — £{listing['rent_pcm']} — {listing['bedrooms']} beds")
                try:
                    requests.post(WEBHOOK_URL, json={"text": message}, timeout=10)
                except Exception as e:
                    print(f"⚠️ Failed to POST: {e}")

            sleep_time = 3600 + random.randint(-300, 300)
            print(f"💤 Sleeping {sleep_time}s…")
            await asyncio.sleep(sleep_time)
        except Exception as e:
            print(f"🔥 Error: {e}")
            await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
