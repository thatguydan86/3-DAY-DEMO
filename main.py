import asyncio
import time
import random
import requests
from typing import Dict, List, Set

print("🚀 Starting RentRadar Demo Mode…")

# ========= Config =========
WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

# Location IDs from Rightmove URLs
LOCATION_IDS: Dict[str, str] = {
    "FY1": "OUTCODE^915",
    "PL1": "OUTCODE^2054",
    "PL4": "OUTCODE^2083",
    "LL30": "OUTCODE^1464",
}

# ADR, occupancy, bills by area + bedrooms
AREA_DATA = {
    "FY1": {
        2: {"adr": 125, "occ": 0.50, "bills": 600},
        3: {"adr": 145, "occ": 0.51, "bills": 600},
    },
    "PL1": {
        1: {"adr": 95, "occ": 0.67, "bills": 580},
        2: {"adr": 130, "occ": 0.68, "bills": 580},
    },
    "PL4": {
        1: {"adr": 96, "occ": 0.64, "bills": 580},
        2: {"adr": 120, "occ": 0.65, "bills": 580},
    },
    "LL30": {
        3: {"adr": 167, "occ": 0.63, "bills": 620},
        4: {"adr": 272, "occ": 0.61, "bills": 620},
    },
}

BOOKING_FEE_PCT = 0.15
GOOD_PROFIT_TARGET = 1200  # target for 70% occ

# ========= Helpers =========
def monthly_net_from_adr(adr: float, occ: float) -> float:
    gross = adr * occ * 30
    return gross * (1 - BOOKING_FEE_PCT)

def calculate_profits(rent_pcm: int, area: str, beds: int):
    data = AREA_DATA.get(area, {}).get(beds)
    if not data:
        return None
    adr = data["adr"]
    occ = data["occ"]
    bills = data["bills"]

    def profit(occ_val: float) -> int:
        net_income = monthly_net_from_adr(adr, occ_val)
        return int(round(net_income - rent_pcm - bills))

    return {
        "adr": adr,
        "occ": occ,
        "bills": bills,
        "profit_50": profit(0.50),
        "profit_70": profit(0.70),
        "profit_100": profit(1.00),
    }

def format_whatsapp_message(listing: dict, extra_count: int = 0) -> str:
    tick = "✅" if listing["profit_70"] >= GOOD_PROFIT_TARGET else "❌"
    score10 = round(max(0, min(10, (listing["profit_70"] / GOOD_PROFIT_TARGET) * 10)), 1)
    avg_occ_pct = int(listing["occ"] * 100)

    msg = (
        f"🔔 New Rent-to-SA Lead 🔵\n"
        f"Score: {score10}/10\n\n"
        f"📍 {listing['address']} — {listing['area']}\n"
        f"🏠 {listing['bedrooms']}-bed | 🛁 {listing.get('bathrooms', 'N/A')} baths\n"
        f"💷 Rent: £{listing['rent_pcm']}/mo | 📊 Bills: £{listing['bills']}/mo | 💳 Fees: {int(BOOKING_FEE_PCT*100)}%\n\n"
        f"💰 Profit (ADR £{listing['adr']} / Avg Occ: {avg_occ_pct}%)\n"
        f"• 50% → £{listing['profit_50']}\n"
        f"• 70% → £{listing['profit_70']} {tick} Target £{GOOD_PROFIT_TARGET}\n"
        f"• 100% → £{listing['profit_100']}\n\n"
        f"🔗 View listing: {listing['url']}\n\n"
        f"📌 Estimate figures drawn from Booking.com, AirBnB & Property Market Intel.\n"
        f"We advise you do your own due diligence.\n\n"
        f"💡 Want exclusive property leads tailored to you?\n"
        f"We can set up your own personal feed with your exact criteria, target area, and private deals — starting from £29/month.\n"
        f"Sign up at rent-radar.co.uk or email support@rent-radar.co.uk"
    )

    if extra_count > 0:
        msg += f"\n\n⚠️ {extra_count} more matching properties found today — available on the paid plan."

    return msg

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
            beds = prop.get("bedrooms")
            rent = prop.get("price", {}).get("amount")
            baths = prop.get("bathrooms") or "N/A"
            if not beds or not rent:
                continue
            p = calculate_profits(rent, area, beds)
            if not p:
                continue
            image_url = None
            if prop.get("propertyImages") and prop["propertyImages"].get("mainImageSrc"):
                image_url = prop["propertyImages"]["mainImageSrc"]
            listing = {
                "id": prop.get("id"),
                "area": area,
                "address": prop.get("displayAddress", "Unknown"),
                "rent_pcm": rent,
                "bedrooms": beds,
                "bathrooms": baths,
                "url": f"https://www.rightmove.co.uk{prop.get('propertyUrl')}",
                "adr": p["adr"],
                "occ": p["occ"],
                "bills": p["bills"],
                "profit_50": p["profit_50"],
                "profit_70": p["profit_70"],
                "profit_100": p["profit_100"],
                "image_url": image_url,
            }
            results.append(listing)
        except Exception:
            continue
    return results

# ========= Scraper loop =========
async def scrape_once(seen_ids: Set[str]) -> List[Dict]:
    all_new_listings = []
    for area, loc_id in LOCATION_IDS.items():
        print(f"\n📍 Searching {area}…")
        raw_props = fetch_properties(loc_id)
        filtered = filter_properties(raw_props, area)
        for listing in filtered:
            if listing["id"] in seen_ids:
                continue
            seen_ids.add(listing["id"])
            all_new_listings.append(listing)
    return all_new_listings

async def main() -> None:
    print("🚀 Demo scraper started! (2 leads/day max)")
    seen_ids: Set[str] = set()
    while True:
        try:
            print(f"\n⏰ New scrape at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            all_new_listings = await scrape_once(seen_ids)

            # Sort by profit_70 descending
            all_new_listings.sort(key=lambda x: x["profit_70"], reverse=True)

            extra_count = max(0, len(all_new_listings) - 2)
            leads_to_send = all_new_listings[:2]

            for idx, listing in enumerate(leads_to_send):
                msg_text = format_whatsapp_message(listing, extra_count if idx == len(leads_to_send)-1 else 0)
                payload = {
                    "text": msg_text,
                    "image_url": listing["image_url"]
                }
                print(f"✅ Sending lead: {listing['address']} ({listing['area']})")
                try:
                    requests.post(WEBHOOK_URL, json=payload, timeout=10)
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
