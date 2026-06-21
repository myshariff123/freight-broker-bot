"""
Carrier Database Builder — runs once to seed the carrier database.
Sources: Google Places API (free tier), Yellow Pages Canada, public web search.
No load board account required. Builds AB carrier list with contact info + lanes.

Run: docker exec freight-broker-bot python -m carriers.carrier_builder
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
import aiohttp
from tracker.database import SessionLocal, init_db
from carriers.models import Carrier, CarrierLane

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

AB_SEARCH_CITIES = [
    "Calgary Alberta", "Edmonton Alberta", "Red Deer Alberta",
    "Lethbridge Alberta", "Grande Prairie Alberta", "Fort McMurray Alberta",
    "Lloydminster Alberta", "Medicine Hat Alberta", "Airdrie Alberta",
]

SEARCH_TERMS = [
    "trucking company",
    "freight carrier",
    "transport company",
    "logistics company",
]

# Yellow Pages Canada — publicly scrapeable
YP_SEARCH_URL = "https://www.yellowpages.ca/search/si/1/{query}/{location}"


class CarrierBuilder:
    def __init__(self):
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

    async def stop(self):
        if self.session:
            await self.session.close()

    async def build_from_google_places(self) -> list[dict]:
        """Use Google Places API to find AB trucking companies."""
        if not GOOGLE_API_KEY:
            logger.warning("No GOOGLE_PLACES_API_KEY — skipping Google Places. Set it in .env for better results.")
            return []

        carriers = []
        base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

        for city in AB_SEARCH_CITIES:
            for term in SEARCH_TERMS[:2]:  # Limit to avoid API quota
                query = f"{term} {city}"
                params = {"query": query, "key": GOOGLE_API_KEY, "region": "ca"}

                try:
                    async with self.session.get(base_url, params=params) as resp:
                        data = await resp.json()
                        results = data.get("results", [])

                        for place in results:
                            carrier = await self._place_to_carrier(place, city)
                            if carrier:
                                carriers.append(carrier)

                        logger.info(f"Google: {len(results)} results for '{query}'")
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"Google Places error: {e}")

        return carriers

    async def _place_to_carrier(self, place: dict, city: str) -> dict | None:
        name = place.get("name", "")
        address = place.get("formatted_address", "")
        rating = place.get("rating", 0)
        place_id = place.get("place_id", "")

        # Filter out obvious non-carriers
        skip_keywords = ["school", "restaurant", "hotel", "store", "shop", "retail", "pizza"]
        if any(k in name.lower() for k in skip_keywords):
            return None

        province = self._extract_province(address)
        if province != "AB":
            return None

        # Get details (phone number)
        phone = ""
        website = ""
        if GOOGLE_API_KEY and place_id:
            try:
                detail_url = "https://maps.googleapis.com/maps/api/place/details/json"
                params = {
                    "place_id": place_id,
                    "fields": "formatted_phone_number,website",
                    "key": GOOGLE_API_KEY,
                }
                async with self.session.get(detail_url, params=params) as resp:
                    detail = await resp.json()
                    result = detail.get("result", {})
                    phone = result.get("formatted_phone_number", "")
                    website = result.get("website", "")
                await asyncio.sleep(0.2)
            except Exception:
                pass

        city_name = city.replace(" Alberta", "").strip()

        return {
            "source": "google_places",
            "company_name": name,
            "city": city_name,
            "province": "AB",
            "phone": phone,
            "website": website,
            "google_rating": rating,
            "address": address,
            "typical_equipment": self._guess_equipment(name),
            "home_province": "AB",
        }

    async def build_from_yellowpages(self) -> list[dict]:
        """Scrape Yellow Pages Canada for AB trucking companies."""
        from playwright.async_api import async_playwright

        carriers = []
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()

        search_pairs = [
            ("trucking", "Calgary+AB"),
            ("trucking", "Edmonton+AB"),
            ("freight+transport", "Calgary+AB"),
            ("freight+transport", "Edmonton+AB"),
            ("trucking", "Red+Deer+AB"),
            ("trucking", "Lethbridge+AB"),
        ]

        for term, location in search_pairs:
            url = f"https://www.yellowpages.ca/search/si/1/{term}/{location}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(1)

                listings = await page.query_selector_all(".listing, .result, [class*='listing-card']")
                logger.info(f"YP: {len(listings)} listings for {term} in {location}")

                for listing in listings:
                    try:
                        carrier = await self._parse_yp_listing(listing)
                        if carrier:
                            carriers.append(carrier)
                    except Exception as e:
                        logger.debug(f"YP parse: {e}")

                await asyncio.sleep(1.5)

            except Exception as e:
                logger.error(f"YP scrape error for {term}/{location}: {e}")

        await browser.close()
        await playwright.stop()
        return carriers

    async def _parse_yp_listing(self, listing) -> dict | None:
        name_el = await listing.query_selector(".listing-name, h3, .business-name, a.listing-name")
        phone_el = await listing.query_selector(".phone, [class*='phone'], .number")
        addr_el = await listing.query_selector(".address, [class*='address']")

        if not name_el:
            return None

        name = await name_el.inner_text()
        phone = await phone_el.inner_text() if phone_el else ""
        address = await addr_el.inner_text() if addr_el else ""

        name = name.strip()
        if not name:
            return None

        # Only keep transport/trucking related companies
        transport_keywords = ["truck", "transport", "freight", "carrier", "logistics",
                              "hauling", "haulage", "moving", "express", "delivery"]
        if not any(k in name.lower() for k in transport_keywords):
            return None

        return {
            "source": "yellowpages",
            "company_name": name,
            "city": self._extract_city(address),
            "province": "AB",
            "phone": phone.strip(),
            "website": "",
            "google_rating": 0,
            "address": address.strip(),
            "typical_equipment": self._guess_equipment(name),
            "home_province": "AB",
        }

    def _extract_province(self, address: str) -> str:
        m = re.search(r'\b([A-Z]{2})\b', address)
        return m.group(1) if m else ""

    def _extract_city(self, address: str) -> str:
        parts = [p.strip() for p in address.split(",")]
        return parts[0] if parts else ""

    def _guess_equipment(self, name: str) -> str:
        name_lower = name.lower()
        if any(k in name_lower for k in ["flat", "deck", "heavy"]):
            return "Flatbed"
        if any(k in name_lower for k in ["reefer", "refriger", "cold", "cool", "temp"]):
            return "Reefer"
        if any(k in name_lower for k in ["tanker", "bulk", "liquid"]):
            return "Tanker"
        return "Dry Van"

    def save_to_db(self, carriers: list[dict]):
        db = SessionLocal()
        try:
            added = 0
            skipped = 0
            for c in carriers:
                existing = db.query(Carrier).filter_by(company_name=c["company_name"]).first()
                if existing:
                    skipped += 1
                    continue

                carrier = Carrier(
                    company_name=c["company_name"],
                    city=c.get("city", ""),
                    province=c.get("province", "AB"),
                    phone=c.get("phone", ""),
                    website=c.get("website", ""),
                    address=c.get("address", ""),
                    typical_equipment=c.get("typical_equipment", "Dry Van"),
                    home_province="AB",
                    source=c.get("source", ""),
                    google_rating=c.get("google_rating", 0),
                    status="uncontacted",
                )
                db.add(carrier)
                added += 1

            db.commit()
            logger.info(f"Carrier DB: {added} added, {skipped} already existed")
            return added
        finally:
            db.close()


async def run_build():
    init_db()
    builder = CarrierBuilder()
    await builder.start()

    all_carriers = []

    logger.info("=== Building carrier database ===")

    logger.info("Source 1: Yellow Pages Canada...")
    yp_carriers = await builder.build_from_yellowpages()
    all_carriers.extend(yp_carriers)
    logger.info(f"Yellow Pages: {len(yp_carriers)} carriers found")

    if os.getenv("GOOGLE_PLACES_API_KEY"):
        logger.info("Source 2: Google Places...")
        gp_carriers = await builder.build_from_google_places()
        all_carriers.extend(gp_carriers)
        logger.info(f"Google Places: {len(gp_carriers)} carriers found")
    else:
        logger.info("Source 2: Google Places skipped (add GOOGLE_PLACES_API_KEY to .env for more results)")

    await builder.stop()

    total = builder.save_to_db(all_carriers)
    logger.info(f"=== Done. {total} new carriers saved to database ===")
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_build())
