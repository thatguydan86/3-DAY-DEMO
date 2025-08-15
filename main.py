import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Dict
import requests
from playwright.async_api import async_playwright

# Config
MAX_PRICE = 1300
GOOD_PROFIT_TARGET = 950
BOOKING_FEE_PCT = 0.15
DAILY_SEND_LIMIT = 5
ACTIVE_HOURS = 14  # Spread sends across 14 hours

# Bills per area & bedroom count (whole numbers)
BILLS_PER_AREA: Dict[str, Dict[int, int]] = {
    "FY1": {2: 587, 3: 645, 4: 712},
    "FY2": {2: 590, 3: 648, 4: 715},
    "PL1": {2: 580, 3: 635, 4: 700},
    "PL4": {2: 583, 3: 640, 4: 705},
    "LL30": {2: 570, 3: 625, 4: 690},
    "LL31": {2: 575, 3: 630, 4: 695},
}

# Nightly rates and occupancy per area/bedrooms
NIGHTLY_RATE = {
    "FY1": {2: 125, 3: 145, 4: 160},
    "FY2": {2: 125, 3: 145, 4: 160},
    "PL1": {2: 120, 3: 140, 4: 155},
    "PL4": {2: 120, 3: 140, 4: 155},
    "LL30": {2: 118, 3: 138, 4: 153},
    "LL31": {2: 118, 3: 138, 4: 153},
}

OCCUPANCY_RATE = {
    "FY1": {2: 0.50, 3: 0.51, 4: 0.52},
    "FY2": {2: 0.50, 3: 0.51, 4: 0.52},
    "PL1": {2: 0.49, 3: 0.50, 4: 0.51},
    "PL4": {2: 0.49, 3: 0.50, 4: 0.51},
    "LL30": {2: 0.48, 3: 0.49, 4: 0.50},
    "LL31": {2: 0.48, 3: 0.49, 4: 0.50},
}

SEARCH_URLS = {
    "FY1": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^FY1",
    "FY2": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^FY2",
    "PL1": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^PL1",
    "PL4": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^PL4",
    "LL30": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^LL30",
    "LL31": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^LL31",
}

WEBHOOK_URL = os.getenv("https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4", "")

sent_today = []
start_of_day = datetime.now().date()


def reset_daily_limit():
    global sent_today, start_of_day
    if datetime.now().date() != start_of_day:
        sent_today = []
        start_of_day = datetime.now().date()


async def fetch_bathrooms(page, property_url):
    try:
        await page.goto(property_url, timeout=60000)
        text_content = await page.text_content("body")
        # Simple parse: look for "bathroom" in page text
        if text_content:
            text_lower = text_content.lower()
            if "1 bathroom" in text_lower:
                return 1
            elif "2 bathrooms" in text_lower:
                return 2
            elif "3 bathrooms" in text_lower:
                return 3
            elif "4 bathrooms" in text_lower:
                return 4
        return None
    except Exception:
        return None


async def scrape_area(area_code, playwright):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    results = []
    try:
        await page.goto(SEARCH_URLS[area_code], timeout=60000)
        cards = page.locator("div[data-test='propertyCard']")

        count = await cards.count()
        for i in range(count):
            card = cards.nth(i)

            price_text = await card.locator("div[propertyCard-priceValue]").text_content()
            if not price_text:
                continue
            price = int("".join(filter(str.isdigit, price_text)))
            if price > MAX_PRICE:
                continue

            address = await card.locator("address").text_content()
            link = await card.locator("a").first.get_attribute("href")
            if not link:
                continue
            full_url = "https://www.rightmove.co.uk" + link

            bed_text = await card.locator("h2").text_content()
            bedrooms = None
            if bed_text:
                for num in range(1, 6):
                    if f"{num} bedroom" in bed_text.lower():
                        bedrooms = num
                        break
            if not bedrooms:
                continue

            bills = BILLS_PER_AREA.get(area_code, {}).get(bedrooms, 600)
            night_rate = NIGHTLY_RATE.get(area_code, {}).get(bedrooms, 120)
            occ_rate = OCCUPANCY_RATE.get(area_code, {}).get(bedrooms, 0.5)

            bathrooms = await fetch_bathrooms(page, full_url) or 1

            gross_100 = night_rate * 30 * 1.0
            gross_70 = night_rate * 30 * 0.7
            gross_50 = night_rate * 30 * 0.5

            profit_100 = int(gross_100 * (1 - BOOKING_FEE_PCT) - price - bills)
            profit_70 = int(gross_70 * (1 - BOOKING_FEE_PCT) - price - bills)
            profit_50 = int(gross_50 * (1 - BOOKING_FEE_PCT) - price - bills)

            results.append({
                "area": area_code,
                "address": address.strip() if address else "",
                "rent_pcm": price,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "night_rate": night_rate,
                "occ_rate": int(occ_rate * 100),
                "bills": bills,
                "profit_50": profit_50,
                "profit_70": profit_70,
                "profit_100": profit_100,
                "target_profit_70": GOOD_PROFIT_TARGET,
                "score10": round((profit_70 / GOOD_PROFIT_TARGET) * 10, 1),
                "rag": "🟢" if profit_70 >= GOOD_PROFIT_TARGET else "🔴",
                "url": full_url
            })
    finally:
        await browser.close()

    return results


async def main():
    global sent_today
    async with async_playwright() as p:
        all_results = []
        for area in SEARCH_URLS:
            all_results.extend(await scrape_area(area, p))

        reset_daily_limit()

        remaining_slots = DAILY_SEND_LIMIT - len(sent_today)
        if remaining_slots <= 0:
            print("Daily send limit reached.")
            return

        to_send = all_results[:remaining_slots]

        if not to_send:
            print("No properties found to send.")
            return

        interval = (ACTIVE_HOURS * 3600) / len(to_send)

        for idx, prop in enumerate(to_send):
            requests.post(WEBHOOK_URL, json=prop)
            sent_today.append(prop)
            if idx < len(to_send) - 1:
                time.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
