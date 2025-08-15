import asyncio
from playwright.async_api import async_playwright
import requests
from datetime import datetime
import re

# Search areas and URLs
search_urls = {
    "FY1": "YOUR_RIGHTMOVE_URL",
    "FY2": "YOUR_RIGHTMOVE_URL",
    "PL1": "YOUR_RIGHTMOVE_URL",
    "PL4": "YOUR_RIGHTMOVE_URL",
    "LL30": "YOUR_RIGHTMOVE_URL",
    "LL31": "YOUR_RIGHTMOVE_URL"
}

# ADR & occupancy mapping
adr_mapping = {
    "FY1": 125,
    "FY2": 125,
    "PL1": 130,
    "PL4": 120,
    "LL30": 100,
    "LL31": 100
}

occ_mapping = {
    "FY1": 0.60,
    "FY2": 0.60,
    "PL1": 0.68,
    "PL4": 0.65,
    "LL30": 0.60,
    "LL31": 0.60
}

# Duplicate tracker
sent_ids = set()

# Telegram webhook URL
make_webhook_url = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

# Filter keywords
exclude_keywords = ["HMO", "House share", "Flat share", "Room to rent", "Shared accommodation"]

async def scrape_area(page, area, url):
    print(f"📍 Searching {area}…")
    await page.goto(url)
    await page.wait_for_selector("div[data-test='propertyCard']", timeout=10000)
    cards = await page.query_selector_all("div[data-test='propertyCard']")

    if not cards:
        print(f"⚠️ No properties found for {area}.")
        return

    found_count = 0
    sent_count = 0
    skipped_duplicates = 0
    skipped_keywords = 0

    for card in cards:
        found_count += 1

        # Extract Rightmove property ID
        link_el = await card.query_selector("a[data-test='propertyCard-link']")
        href = await link_el.get_attribute("href") if link_el else ""
        property_id_match = re.search(r"/(\d+)", href or "")
        property_id = property_id_match.group(1) if property_id_match else None

        if not property_id or property_id in sent_ids:
            skipped_duplicates += 1
            continue

        # Extract title for keyword filtering
        title_el = await card.query_selector("h2")
        title = (await title_el.inner_text()).strip() if title_el else ""

        if any(kw.lower() in title.lower() for kw in exclude_keywords):
            skipped_keywords += 1
            continue

        # Extract price
        price_el = await card.query_selector("div[data-test='propertyCard-priceValue']")
        price_text = (await price_el.inner_text()).strip() if price_el else ""
        price_match = re.search(r"£([\d,]+)", price_text)
        rent_pcm = int(price_match.group(1).replace(",", "")) if price_match else 0

        # Extract bedrooms
        bed_el = await card.query_selector("h2")
        bed_text = (await bed_el.inner_text()).strip() if bed_el else ""
        bed_match = re.search(r"(\d+)\s*-?bed", bed_text, re.IGNORECASE)
        bedrooms = int(bed_match.group(1)) if bed_match else None

        # Profit calculations
        adr = adr_mapping.get(area, 100)
        occ_rate = occ_mapping.get(area, 0.6)
        occ_display = int(occ_rate * 100)  # Show as whole number %

        bills = 600
        fees_pct = 0.15
        monthly_income = adr * 30 * occ_rate
        profit_50 = int(adr * 30 * 0.5 - rent_pcm - bills - (adr * 30 * 0.5 * fees_pct))
        profit_70 = int(adr * 30 * 0.7 - rent_pcm - bills - (adr * 30 * 0.7 * fees_pct))
        profit_100 = int(adr * 30 * 1.0 - rent_pcm - bills - (adr * 30 * 1.0 * fees_pct))

        # Send to Make webhook
        payload = {
            "id": property_id,
            "area": area,
            "address": title,
            "rent_pcm": rent_pcm,
            "bedrooms": bedrooms,
            "night_rate": adr,
            "occ_rate": occ_display,
            "bills": bills,
            "profit_50": profit_50,
            "profit_70": profit_70,
            "profit_100": profit_100,
            "target_profit_70": 1200,
            "score10": 10,
            "rag": "🟢",
            "url": f"https://www.rightmove.co.uk/properties/{property_id}"
        }
        requests.post(make_webhook_url, json=payload)
        sent_ids.add(property_id)
        sent_count += 1

    print(f"✅ {area}: Found {found_count}, Sent {sent_count}, Skipped duplicates {skipped_duplicates}, Skipped keywords {skipped_keywords}")

async def main():
    print("🚀 Starting RentRadar…\n")
    while True:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            for area, url in search_urls.items():
                await scrape_area(page, area, url)

            await browser.close()

        sleep_time = 3600  # 1 hour
        print(f"💤 Sleeping {sleep_time} seconds…\n")
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(main())
