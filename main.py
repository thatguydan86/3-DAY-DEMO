import asyncio
import requests
from playwright.async_api import async_playwright
from typing import Dict

# Telegram Bot Config
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# Webhook for Make.com (optional backup)
WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

# Bills per area & bedroom count (realistic estimates, excl. waste/TVL/insurance)
BILLS_PER_AREA: Dict[str, Dict[int, int]] = {
    "FY1": {1: 380, 2: 420, 3: 450},
    "FY2": {1: 380, 2: 420, 3: 450},
    "FY3": {1: 380, 2: 420, 3: 450},
    "FY4": {1: 380, 2: 420, 3: 450},
    "PL1": {1: 380, 2: 420},
    "PL4": {1: 380, 2: 420},
    "LL30": {3: 450, 4: 480},
    "LL31": {3: 450, 4: 480},
}

# ADR + Occupancy defaults (per area + bedrooms)
NIGHTLY_RATES: Dict[str, Dict[int, Dict[str, float]]] = {
    "FY1": {
        1: {"adr": 93, "occ": 0.53},
        2: {"adr": 110, "occ": 0.55},
        3: {"adr": 135, "occ": 0.57},
    },
    "FY2": {
        1: {"adr": 90, "occ": 0.52},
        2: {"adr": 108, "occ": 0.54},
        3: {"adr": 130, "occ": 0.56},
    },
    "FY3": {
        1: {"adr": 85, "occ": 0.50},
        2: {"adr": 105, "occ": 0.52},
        3: {"adr": 125, "occ": 0.54},
    },
    "FY4": {
        1: {"adr": 87, "occ": 0.56},
        2: {"adr": 115, "occ": 0.58},
        3: {"adr": 140, "occ": 0.60},
    },
}

FEES = 0.15  # Mgmt/cleaning etc.

# Telegram sender
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    requests.post(url, json=payload)

# Profit calculator
def calculate_profit(area: str, bedrooms: int, rent: int) -> Dict[str, float]:
    bills = BILLS_PER_AREA.get(area, {}).get(bedrooms, 420)
    adr = NIGHTLY_RATES.get(area, {}).get(bedrooms, {}).get("adr", 100)
    occ = NIGHTLY_RATES.get(area, {}).get(bedrooms, {}).get("occ", 0.6)

    monthly_income = adr * 30 * occ
    management_fees = monthly_income * FEES
    net_income = monthly_income - rent - bills - management_fees

    return {
        "adr": adr,
        "occ": occ,
        "bills": bills,
        "rent": rent,
        "fees": management_fees,
        "net": net_income,
        "profit_50": (adr * 30 * 0.5) - rent - bills - ((adr * 30 * 0.5) * FEES),
        "profit_70": (adr * 30 * 0.7) - rent - bills - ((adr * 30 * 0.7) * FEES),
        "profit_100": (adr * 30 * 1.0) - rent - bills - ((adr * 30 * 1.0) * FEES),
    }

# Main scraper loop
async def scrape_rightmove():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=REGION%5E93917")  # example search

        props = await page.query_selector_all("div[data-test='propertyCard']")

        for prop in props:
            try:
                title = await prop.query_selector_eval("h2", "el => el.innerText")
                price_text = await prop.query_selector_eval("div[data-test='propertyCard-price']", "el => el.innerText")
                url = await prop.query_selector_eval("a", "el => el.href")

                rent = int(price_text.replace("£", "").replace(",", "").split()[0])
                area = "FY1"  # placeholder: parse from address in real use
                bedrooms = 1   # placeholder: parse properly from listing

                profit = calculate_profit(area, bedrooms, rent)

                message = (
                    f"📢 <b>New Rent-to-SA Lead</b>\n"
                    f"💡 <b>ADR:</b> £{profit['adr']} | <b>Occ:</b> {int(profit['occ']*100)}%\n"
                    f"🏠 {title}\n"
                    f"💷 Rent: £{rent}/mo | 📊 Bills: £{profit['bills']}/mo | 🧾 Fees: 15%\n\n"
                    f"💰 Profit Scenarios:\n"
                    f"• 50% → £{int(profit['profit_50'])}\n"
                    f"• 70% → £{int(profit['profit_70'])}\n"
                    f"• 100% → £{int(profit['profit_100'])}\n\n"
                    f"🔗 <a href='{url}'>View listing</a>"
                )

                send_telegram(message)

            except Exception as e:
                print("⚠️ Error filtering property:", e)

        await browser.close()

if __name__ == "__main__":
    print("🚀 Starting RentRadar DEMO…")
    asyncio.run(scrape_rightmove())
