import asyncio
import json
import os
import re
import requests
from playwright.async_api import async_playwright

WEBHOOK_URL = os.getenv("https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4")

# --- Hardcoded nightly & occupancy rates (safe estimates) ---
NIGHTLY_RATES = {
    "FY1": {1: 105, 2: 120, 3: 145, 4: 160},
    "FY4": {1: 87, 2: 110, 3: 140, 4: 155},
}
OCCUPANCY = {
    "FY1": 65,
    "FY4": 56,
}

# --- Utility functions ---
def extract_number(text):
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None

def calculate_profits(rent, bills, night_rate, occ_rate):
    fees = 0.15
    occ = occ_rate / 100

    monthly_income = night_rate * 30
    gross = {
        50: monthly_income * 0.5,
        70: monthly_income * 0.7,
        100: monthly_income * 1.0,
    }

    net = {}
    for occ_level, income in gross.items():
        after_fees = income * (1 - fees)
        net[occ_level] = round(after_fees - (rent + bills))
    return net

# --- Main scraper ---
async def scrape_rightmove(playwright):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    search_urls = {
        "FY1": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^FY1",
        "FY4": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE^FY4",
    }

    for area, url in search_urls.items():
        print(f"📍 Searching {area}…")
        await page.goto(url)
        await page.wait_for_selector("div[data-test='propertyCard']", timeout=15000)

        cards = await page.query_selector_all("div[data-test='propertyCard']")
        if not cards:
            print(f"❌ NO PROPERTIES FOUND for {area}")
            continue

        for card in cards[:5]:  # limit results for demo
            address = await card.query_selector_eval("address", "el => el.innerText") if await card.query_selector("address") else "Unknown"
            rent_text = await card.query_selector_eval("span.propertyCard-priceValue", "el => el.innerText") if await card.query_selector("span.propertyCard-priceValue") else "£0"
            rent = int(re.sub(r"[^\d]", "", rent_text)) if rent_text else 0

            bed_text = await card.query_selector_eval("h2", "el => el.innerText") if await card.query_selector("h2") else "0"
            bedrooms = extract_number(bed_text) or 1

            bath_text = await card.query_selector_eval("h2", "el => el.innerText") if await card.query_selector("h2") else "0"
            bathrooms = extract_number(bath_text) or 1   # 👈 new bathrooms field

            url_link = await card.query_selector_eval("a", "el => el.href") if await card.query_selector("a") else "#"

            night_rate = NIGHTLY_RATES.get(area, {}).get(bedrooms, 100)
            occ_rate = OCCUPANCY.get(area, 60)
            bills = 420

            profits = calculate_profits(rent, bills, night_rate, occ_rate)

            data = {
                "area": area,
                "address": address,
                "rent_pcm": rent,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,   # 👈 now sent to webhook
                "night_rate": night_rate,
                "occ_rate": occ_rate,
                "bills": bills,
                "profit_50": profits[50],
                "profit_70": profits[70],
                "profit_100": profits[100],
                "target_profit_70": 950,
                "score10": 9.5,
                "rag": "🟢",
                "url": url_link,
            }

            print(f"🚀 Sending {address} → Webhook")
            requests.post(WEBHOOK_URL, json=data)

    await browser.close()

async def main():
    async with async_playwright() as playwright:
        await scrape_rightmove(playwright)

if __name__ == "__main__":
    asyncio.run(main())
