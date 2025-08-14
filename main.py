import requests

# === DEMO SETTINGS ===
DEMO_POSTCODES = {
    "FY1": {"adr": 145, "avg_occ": 51, "bills": 395},
    "PL1": {"adr": 150, "avg_occ": 54, "bills": 420},
    "LL30": {"adr": 140, "avg_occ": 49, "bills": 380}
}

TARGET_PROFIT = 1200
TELEGRAM_WEBHOOK_URL = "https://hook.eu2.make.com/m4n56tg2c1txony43nlyjrrsykkf7ij4"

def calc_profit(adr, occ_percent, rent, bills, fees_percent):
    monthly_revenue = adr * (30 * occ_percent / 100)
    fees = (monthly_revenue * fees_percent) / 100
    return round(monthly_revenue - rent - bills - fees)

def format_telegram_message(score, location, bedrooms, bathrooms, rent, bills, fees_percent, adr, avg_occ, listing_url, matching_url):
    profit_50 = calc_profit(adr, 50, rent, bills, fees_percent)
    profit_70 = calc_profit(adr, 70, rent, bills, fees_percent)
    profit_100 = calc_profit(adr, 100, rent, bills, fees_percent)
    tick = "✅" if profit_70 >= TARGET_PROFIT else ""

    return f"""🔔 New Rent-to-SA Lead 🔵
Score: {score}/10

📍 {location}
🏡 {bedrooms}-bed | 🛁 {bathrooms} baths
💰 Rent: £{rent}/mo | 📊 Bills: £{bills}/mo | 🧾 Fees: {fees_percent}%

💵 Profit (ADR £{adr} / Avg Occ: {avg_occ}%)
• 50% → £{profit_50}
• 70% → £{profit_70} {tick} Target £{TARGET_PROFIT}
• 100% → £{profit_100}

🔗 View listing: {listing_url}

📌 Estimate figures drawn from Booking.com, AirBnB & Property Market Intel.
We advise you do your own due diligence.

💡 Want exclusive property leads tailored to you?
We can set up your own personal feed with your exact criteria, target area, and private deals — starting from £29/month.
Sign up at rent-radar.co.uk or email support@rent-radar.co.uk

📍 More matching properties: {matching_url}
"""

def send_to_telegram(message):
    payload = {"text": message}
    requests.post(TELEGRAM_WEBHOOK_URL, json=payload)

# === DEMO LEAD EXAMPLE ===
demo_leads = [
    {"postcode": "FY1", "score": 10, "location": "Cunliffe Road, Blackpool, Lancashire, FY1 — Blackpool", "bedrooms": 3, "bathrooms": 1, "rent": 850, "fees_percent": 15, "listing_url": "https://www.rightmove.co.uk/properties/165767510#/?channel=RES_LET", "matching_url": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE%5EFY1"},
    {"postcode": "PL1", "score": 8.9, "location": "Example Street, Plymouth, PL1 — Plymouth", "bedrooms": 4, "bathrooms": 2, "rent": 1500, "fees_percent": 15, "listing_url": "https://www.rightmove.co.uk/properties/example", "matching_url": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE%5EPL1"},
    {"postcode": "LL30", "score": 8.4, "location": "Another Street, Llandudno, LL30 — Llandudno", "bedrooms": 3, "bathrooms": 1, "rent": 900, "fees_percent": 15, "listing_url": "https://www.rightmove.co.uk/properties/example2", "matching_url": "https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=POSTCODE%5ELL30"}
]

# Run demo mode
for lead in demo_leads:
    if lead["postcode"] in DEMO_POSTCODES:
        adr = DEMO_POSTCODES[lead["postcode"]]["adr"]
        avg_occ = DEMO_POSTCODES[lead["postcode"]]["avg_occ"]
        bills = DEMO_POSTCODES[lead["postcode"]]["bills"]

        msg = format_telegram_message(
            lead["score"],
            lead["location"],
            lead["bedrooms"],
            lead["bathrooms"],
            lead["rent"],
            bills,
            lead["fees_percent"],
            adr,
            avg_occ,
            lead["listing_url"],
            lead["matching_url"]
        )
        send_to_telegram(msg)
