"""
Freightera scraper (freightera.com) — Canadian freight marketplace.
Vancouver-based, no MC# or DOT required, strong AB lanes.
Register at: https://www.freightera.com (Freight Broker / 3PL account)

Freightera is a marketplace — loads come from shippers posting spot freight.
Login URL: https://www.freightera.com/login
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

FREIGHTERA_URL = "https://www.freightera.com"
SCREENSHOT_DIR = Path("/app/screenshots")
DEBUG = os.getenv("DEBUG_SCREENSHOTS", "false").lower() == "true"


async def take_debug_screenshot(page: Page, name: str):
    if DEBUG:
        path = SCREENSHOT_DIR / f"ft_{name}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(path))
        logger.info(f"Screenshot: {path}")


class FreighteraScraper:
    def __init__(self):
        self.email = os.getenv("FREIGHTERA_EMAIL") or os.getenv("LOADLINK_EMAIL")
        self.password = os.getenv("FREIGHTERA_PASSWORD") or os.getenv("LOADLINK_PASSWORD")
        self.browser = None
        self.context = None
        self.page = None
        self.logged_in = False

    async def start(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        self.page = await self.context.new_page()

    async def login(self) -> bool:
        try:
            logger.info("Logging into Freightera...")
            await self.page.goto(f"{FREIGHTERA_URL}/login", wait_until="networkidle", timeout=30000)
            await take_debug_screenshot(self.page, "01_login")

            await self.page.fill('input[type="email"], input[name="email"], #email', self.email)
            await self.page.fill('input[type="password"], input[name="password"], #password', self.password)
            await self.page.click('button[type="submit"], .login-btn, button:has-text("Sign In")')
            await self.page.wait_for_load_state("networkidle", timeout=20000)
            await take_debug_screenshot(self.page, "02_after_login")

            if "login" not in self.page.url.lower():
                self.logged_in = True
                logger.info("Freightera login successful")
                return True

            logger.error(f"Freightera login failed. URL: {self.page.url}")
            return False

        except Exception as e:
            logger.error(f"Freightera login error: {e}")
            return False

    async def search_alberta_loads(self) -> list[dict]:
        """Search available spot loads originating from Alberta."""
        try:
            # Navigate to spot freight / available loads
            await self.page.goto(
                f"{FREIGHTERA_URL}/broker/loads?origin_province=AB&origin_country=CA",
                wait_until="networkidle",
                timeout=20000
            )
            await take_debug_screenshot(self.page, "03_loads")

            # If above URL doesn't work, try the main loads page and filter
            if "loads" not in self.page.url:
                await self.page.goto(f"{FREIGHTERA_URL}/broker/loads", wait_until="networkidle", timeout=20000)
                try:
                    await self.page.select_option(
                        'select[name*="province"], select[name*="origin"]', "AB"
                    )
                    await self.page.click('button:has-text("Search"), button:has-text("Filter")')
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

            await take_debug_screenshot(self.page, "04_filtered")
            return await self._extract_loads()

        except Exception as e:
            logger.error(f"Freightera search error: {e}")
            return []

    async def _extract_loads(self) -> list[dict]:
        loads = []

        try:
            await self.page.wait_for_selector(
                '.load-card, .load-item, .freight-item, table tbody tr, [class*="load-row"]',
                timeout=10000
            )
        except PWTimeout:
            logger.warning("Freightera: no loads found on page")
            await take_debug_screenshot(self.page, "warn_empty")
            return loads

        rows = await self.page.query_selector_all(
            '.load-card, .load-item, .freight-item, table tbody tr'
        )
        logger.info(f"Freightera: {len(rows)} load rows")

        for row in rows:
            try:
                load = await self._parse_row(row)
                if load:
                    loads.append(load)
            except Exception as e:
                logger.debug(f"Freightera row parse: {e}")

        return loads

    async def _parse_row(self, row) -> dict | None:
        text = await row.inner_text()
        if not text.strip():
            return None

        load_id = await row.get_attribute("data-id") or f"ft_{hash(text[:60])}"
        cells = await row.query_selector_all("td, .cell, [class*='col'], p, span")
        cell_texts = [await c.inner_text() for c in cells]

        if len(cell_texts) < 2:
            return None

        # Freightera card layout varies — try multiple extraction strategies
        origin_city, origin_prov, dest_city, dest_prov = self._extract_route(text, cell_texts)

        if not origin_city:
            return None

        return {
            "loadlink_id": f"ft_{load_id}",
            "source": "Freightera",
            "origin_city": origin_city,
            "origin_province": origin_prov,
            "destination_city": dest_city,
            "destination_province": dest_prov,
            "equipment_type": self._extract_equipment(text),
            "weight_lbs": self._extract_weight(text),
            "distance_km": 0,
            "shipper_rate": self._extract_rate(text),
            "pickup_date": self._extract_date(text),
            "shipper_name": "",
            "raw_data": json.dumps(cell_texts[:10]),
        }

    def _extract_route(self, full_text: str, cells: list) -> tuple:
        """Extract origin/destination from text or cells."""
        import re

        # Pattern: "City, AB → City, BC" or "City (AB) to City (BC)"
        arrow_match = re.search(
            r'([A-Za-z\s]+),?\s*([A-Z]{2})\s*(?:→|->|to)\s*([A-Za-z\s]+),?\s*([A-Z]{2})',
            full_text
        )
        if arrow_match:
            return (
                arrow_match.group(1).strip(),
                arrow_match.group(2).strip(),
                arrow_match.group(3).strip(),
                arrow_match.group(4).strip(),
            )

        # Fallback: first two cells with location format
        if len(cells) >= 2:
            o_city, o_prov = self._split_location(cells[0])
            d_city, d_prov = self._split_location(cells[1])
            if o_city and d_city:
                return o_city, o_prov, d_city, d_prov

        return "", "", "", ""

    def _split_location(self, text: str) -> tuple:
        text = text.strip()
        import re
        m = re.search(r'^(.+?),?\s*([A-Z]{2})$', text)
        if m:
            return m.group(1).strip(), m.group(2)
        parts = text.split()
        if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
            return " ".join(parts[:-1]), parts[-1].upper()
        return text, "AB"

    def _extract_equipment(self, text: str) -> str:
        import re
        m = re.search(r'(Dry Van|Flatbed|Reefer|Step Deck|Van|Flat|Ref|Tanker|B-Train)', text, re.I)
        return m.group(1).title() if m else "Dry Van"

    def _extract_weight(self, text: str) -> int:
        import re
        m = re.search(r'(\d[\d,]*)\s*(?:lbs?|pounds?|kg)', text, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
        return 0

    def _extract_rate(self, text: str) -> float:
        import re
        m = re.search(r'\$\s*([\d,]+(?:\.\d{2})?)', text)
        if m:
            return float(m.group(1).replace(",", ""))
        return 0.0

    def _extract_date(self, text: str) -> str:
        import re
        m = re.search(r'(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4})', text)
        return m.group(1) if m else ""

    async def stop(self):
        if self.browser:
            await self.browser.close()
