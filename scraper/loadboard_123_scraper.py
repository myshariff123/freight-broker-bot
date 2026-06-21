"""
123Loadboard scraper (123loadboard.com) — instant registration, free tier.
Strong Canadian coverage. Register at: https://www.123loadboard.com/register

Free plan gives: 25 searches/day, full load details, contact info visible.
Upgrade ($35/month) removes the search cap entirely.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

LB123_URL = "https://www.123loadboard.com"
SCREENSHOT_DIR = Path("/app/screenshots")
DEBUG = os.getenv("DEBUG_SCREENSHOTS", "false").lower() == "true"


async def take_debug_screenshot(page: Page, name: str):
    if DEBUG:
        path = SCREENSHOT_DIR / f"123lb_{name}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(path))


class LoadBoard123Scraper:
    def __init__(self):
        self.email = os.getenv("LB123_EMAIL") or os.getenv("LOADLINK_EMAIL")
        self.password = os.getenv("LB123_PASSWORD") or os.getenv("LOADLINK_PASSWORD")
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
            logger.info("Logging into 123Loadboard...")
            await self.page.goto(f"{LB123_URL}/Account/Login", wait_until="networkidle", timeout=30000)
            await take_debug_screenshot(self.page, "01_login")

            await self.page.fill('#Email, input[name="Email"], input[type="email"]', self.email)
            await self.page.fill('#Password, input[name="Password"], input[type="password"]', self.password)
            await self.page.click('button[type="submit"], input[type="submit"]')
            await self.page.wait_for_load_state("networkidle", timeout=20000)
            await take_debug_screenshot(self.page, "02_after_login")

            if "Account/Login" not in self.page.url:
                self.logged_in = True
                logger.info("123Loadboard login successful")
                return True

            logger.error(f"123Loadboard login failed. URL: {self.page.url}")
            return False

        except Exception as e:
            logger.error(f"123Loadboard login error: {e}")
            return False

    async def search_alberta_loads(self) -> list[dict]:
        """Search loads from Alberta."""
        try:
            # 123Loadboard search URL with province filter
            search_url = f"{LB123_URL}/Loads/Search?originProvince=AB&originCountry=CA&type=Load"
            await self.page.goto(search_url, wait_until="networkidle", timeout=20000)
            await take_debug_screenshot(self.page, "03_results")

            return await self._extract_loads()

        except Exception as e:
            logger.error(f"123LB search error: {e}")
            return []

    async def _extract_loads(self) -> list[dict]:
        loads = []

        try:
            await self.page.wait_for_selector(
                '.load-item, .search-result, table.loads tbody tr, [class*="load-row"]',
                timeout=10000
            )
        except PWTimeout:
            logger.warning("123LB: no results found")
            return loads

        rows = await self.page.query_selector_all(
            '.load-item, .search-result, table.loads tbody tr'
        )

        for row in rows:
            try:
                load = await self._parse_row(row)
                if load:
                    loads.append(load)
            except Exception as e:
                logger.debug(f"123LB parse: {e}")

        return loads

    async def _parse_row(self, row) -> dict | None:
        text = await row.inner_text()
        if not text.strip():
            return None

        load_id = await row.get_attribute("data-id") or f"123lb_{hash(text[:60])}"
        cells = await row.query_selector_all("td, .cell")
        cell_texts = [await c.inner_text() for c in cells]

        if len(cell_texts) < 3:
            return None

        # 123LB typical: Date | Origin | Dest | Equipment | Weight | Rate | Broker
        date_text = cell_texts[0] if len(cell_texts) > 0 else ""
        origin_text = cell_texts[1] if len(cell_texts) > 1 else ""
        dest_text = cell_texts[2] if len(cell_texts) > 2 else ""
        equip_text = cell_texts[3] if len(cell_texts) > 3 else "Dry Van"
        weight_text = cell_texts[4] if len(cell_texts) > 4 else ""
        rate_text = cell_texts[5] if len(cell_texts) > 5 else ""
        broker_text = cell_texts[6] if len(cell_texts) > 6 else ""

        origin_city, origin_prov = self._split_location(origin_text)
        dest_city, dest_prov = self._split_location(dest_text)

        if not origin_city:
            return None

        return {
            "loadlink_id": f"123lb_{load_id}",
            "source": "123Loadboard",
            "origin_city": origin_city,
            "origin_province": origin_prov,
            "destination_city": dest_city,
            "destination_province": dest_prov,
            "equipment_type": equip_text.strip() or "Dry Van",
            "weight_lbs": self._parse_weight(weight_text),
            "distance_km": 0,
            "shipper_rate": self._parse_rate(rate_text),
            "pickup_date": date_text.strip(),
            "shipper_name": broker_text.strip(),
            "raw_data": json.dumps(cell_texts),
        }

    def _split_location(self, text: str) -> tuple[str, str]:
        text = text.strip()
        parts = [p.strip() for p in text.replace(",", " ").split()]
        for i in range(len(parts) - 1, -1, -1):
            if len(parts[i]) == 2 and parts[i].isalpha():
                return " ".join(parts[:i]), parts[i].upper()
        return text, "AB"

    def _parse_weight(self, text: str) -> int:
        text = text.replace(",", "").replace("lbs", "").strip()
        try:
            return int(float(text))
        except Exception:
            return 0

    def _parse_rate(self, text: str) -> float:
        text = text.replace("$", "").replace(",", "").strip()
        if not text or any(x in text.lower() for x in ["call", "neg", "tbd", "-"]):
            return 0.0
        try:
            return float(text)
        except Exception:
            return 0.0

    async def stop(self):
        if self.browser:
            await self.browser.close()
