import asyncio
import json
import os
import re
import time
import requests
from playwright.async_api import async_playwright

WEBHOOK_URL = os.getenv("https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4")
SEARCH_URLS = [
    # Your Rightmove search URLs here
]

SENT_IDS_FILE = "sent_ids.json"

def load_sent_ids():
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_sent_ids(sent_ids):
    with open(SENT_IDS_FILE, "w") as f:
        json.dump(list(sent_ids), f)

async def scrape_area(playwright, url):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url)

    await page.wait_for_selector("div[data-test='propertyCard']")

    cards = await page.query_selector_all("div[data-test='propertyCard']")
    results = []

    for card in cards:
        try:
            url_elem = await card.query_selector("a[data-test='property-card-link']")
            property_url = "https://www.rightmove.co.uk" + await url_elem.get_attribute("href")
            property_id = re.search(r"/(\d+)", property_url).group(1)

            title_elem = await card.query_selector("address")
            address = await title_elem.inner_text() if title_elem else "Unknown"

            price_elem = await card.query_selector("div[data-test='propertyCard-priceValue']")
            price_text = await price_elem.inner_text()
            rent_pcm = int(re.sub(r"[^\d]", "", price_text))

            bed_elem = await card.query_selector("h2")
            bed_text = await bed_elem.inner_text() if bed_elem else ""
            bedrooms_match = re.search(r"(\d+)\s*-?\s*bed", bed_text.lower())
            bedrooms = int(bedrooms_match.group(1)) if bedrooms_match else 0

            # Example: occupancy calculation (FIX: now sends percentage)
            occ_rate = 0.6  # This would come from your ADR/PMI logic
            occ_percent = int(occ_rate * 100)

            night_rate = 100  # Replace with actual ADR logic

            bills = 600
            fees_percent = 15
            fees_value = (fees_percent / 100) * (rent_pcm + bills)

            def calc_profit(rate, occ):
                return int((rate * occ * 30) - rent_pcm - bills - fees_value)

            profit_50 = calc_profit(night_rate, 0.5)
            profit_70 = calc_profit(night_rate, 0.7)
            profit_100 = calc_profit(night_rate, 1.0)
            target_profit_70 = 1200

            score10 = 7.3
            rag = "🟢" if score10 >= 7 else "🟡"

            results.append({
                "id": property_id,
                "area": url.split("&locationIdentifier=")[-1] if "&locationIdentifier=" in url else "",
                "address": address,
                "rent_pcm": rent_pcm,
                "bedrooms": bedrooms,
                "night_rate": night_rate,
                "occ_rate": occ_percent,  # FIX: sends as int percentage
                "bills": bills,
                "profit_50": profit_50,
                "profit_70": profit_70,
                "profit_100": profit_100,
                "target_profit_70": target_profit_70,
                "score10": score10,
                "rag": rag,
                "url": property_url
            })

        except Exception as e:
            print(f"❌ Error parsing card: {e}")

    await browser.close()
    return results

async def main():
    sent_ids = load_sent_ids()
    async with async_playwright() as p:
        for url in SEARCH_URLS:
            area_results = await scrape_area(p, url)
            for prop in area_results:
                if prop["id"] not in sent_ids:
                    requests.post(WEBHOOK_URL, json=prop)
                    sent_ids.add(prop["id"])
                    print(f"✅ Sent: {prop['address']}")
                else:
                    print(f"⏩ Skipped duplicate: {prop['address']}")
    save_sent_ids(sent_ids)

if __name__ == "__main__":
    asyncio.run(main())
