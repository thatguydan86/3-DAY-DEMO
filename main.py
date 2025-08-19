import asyncio
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Any

import requests
from playwright.async_api import async_playwright

# ---------------- CONFIG ---------------- #
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://hook.integromat.com/xxxx")
BOT_NAME = "RentRadar DEMO"

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

# Round robin demo areas → cycle all of them
DEMO_AREAS: List[str] = list(LOCATION_IDS.keys())
CURRENT_INDEX = 0

MAX_RENT = {
    3: 1300,  # 3-bed cap
    4: 1500   # 4-bed cap
}

BILLS_EST = {
    3: 580,
    4: 850
}

FEES_PC = 0.15


# ---------------- HELPERS ---------------- #
def round_robin_area() -> str:
    """Rotate through demo areas"""
    global CURRENT_INDEX
    area = DEMO_AREAS[CURRENT_INDEX]
    CURRENT_INDEX = (CURRENT_INDEX + 1) % len(DEMO_AREAS)
    return area


def clean_price(text: str) -> int:
    """Convert rent string to int PCM"""
    match = re.search(r"£([\d,]+)", text)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def calc_profits(rent: int, beds: int, nightly_rate: int, occ: float) -> Dict[str, int]:
    bills = BILLS_EST.get(beds, 600)
    occ_rate = occ / 100.0
    gross = nightly_rate * 30 * occ_rate
    fees = gross * FEES_PC
    net = gross - fees - rent - bills
    return {
        "50": int(nightly_rate * 30 * 0.5 - (fees + rent + bills)),
        "70": int(nightly_rate * 30 * 0.7 - (fees + rent + bills)),
        "100": int(nightly_rate * 30 * 1.0 - (fees + rent + bills)),
    }


def score_property(profit70: int) -> (int, str):
    """Assign score and rag"""
    if profit70 > 1000:
        return 10, "🟢"
    elif profit70 > 500:
        return 7, "🟠"
    else:
        return 4, "🔴"


# ---------------- SCRAPER ---------------- #
async def scrape_properties(area: str):
    url = f"https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier={LOCATION_IDS[area]}&maxBedrooms=4&minBedrooms=3&propertyTypes=houses&includeLetAgreed=false&mustHave=&dontShow=&furnishTypes=&keywords="
    print(f"🌍 Scraping {area} → {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=60000)

        await page.wait_for_selector("div.propertyCard", timeout=20000)
        cards = await page.query_selector_all("div.propertyCard")

        results = []
        for card in cards:
            try:
                title = await card.inner_text()
                rent_text = await card.query_selector("span.propertyCard-priceValue")
                rent = clean_price(await rent_text.inner_text()) if rent_text else 0

                # Filter out weekly rents
                if "/week" in title.lower():
                    continue

                beds_match = re.search(r"(\d+)\s+bed", title.lower())
                beds = int(beds_match.group(1)) if beds_match else 0
                if beds not in (3, 4):
                    continue
                if rent == 0 or rent > MAX_RENT.get(beds, 2000):
                    continue

                # Dummy ADR + Occ for demo
                nightly_rate = 145 if beds == 3 else 178
                occ = random.choice([50, 55, 60, 65, 70])
                profits = calc_profits(rent, beds, nightly_rate, occ)

                score, rag = score_property(profits["70"])

                addr = await card.query_selector("address.propertyCard-address")
                address = await addr.inner_text() if addr else "Unknown"

                link_el = await card.query_selector("a.propertyCard-link")
                href = await link_el.get_attribute("href") if link_el else ""
                full_url = f"https://www.rightmove.co.uk{href}" if href else ""

                if not address or not full_url:
                    continue  # skip blanks

                results.append({
                    "address": address,
                    "area": area,
                    "bedrooms": beds,
                    "bathrooms": 1,
                    "rent_pcm": rent,
                    "bills": BILLS_EST.get(beds, 600),
                    "night_rate": nightly_rate,
                    "occ_rate": occ,
                    "profit_50": profits["50"],
                    "profit_70": profits["70"],
                    "profit_100": profits["100"],
                    "target_profit_70": 950 if beds == 3 else 1300,
                    "score10": score,
                    "rag": rag,
                    "url": full_url,
                })
            except Exception as e:
                print(f"⚠️ Error parsing card: {e}")

        await browser.close()
        return results


# ---------------- MAIN ---------------- #
async def main():
    print(f"🚀 Starting {BOT_NAME}…")
    area = round_robin_area()
    listings = await scrape_properties(area)

    for listing in listings:
        payload = json.dumps(listing)
        requests.post(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"})
        print(f"✅ Sent: {listing['address']} — {listing['rent_pcm']}/mo ({listing['score10']}/10 {listing['rag']})")


if __name__ == "__main__":
    asyncio.run(main())
