"""
DAT One scraper (dat.com) — North America's largest load board.
Heavy Canadian coverage: AB→BC, AB→ON, AB→SK lanes.
Free trial at: https://www.dat.com/freight/

DAT uses a React SPA — Playwright handles it correctly.
Login URL: https://dat.com/load-board/loads
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

DAT_URL = "https://dat.com"
SCREENSHOT_DIR = Path("/app/screenshots")
DEBUG = os.getenv("DEBUG_SCREENSHOTS", "false").lower() == "true"

# Alberta city → DAT search string mapping
AB_CITIES = ["Calgary", "Edmonton", "Red Deer", "Lethbridge", "Medicine Hat",
             "Grande Prairie", "Fort McMurray", "Lloydminster"]


async def take_debug_screenshot(page: Page, name: str):
    if DEBUG:
        path = SCREENSHOT_DIR / f"dat_{name}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(path))
        logger.info(f"Screenshot: {path}")


class DATScraper:
    def __init__(self):
        self.email = os.getenv("DAT_EMAIL") or os.getenv("LOADLINK_EMAIL")
        self.password = os.getenv("DAT_PASSWORD") or os.getenv("LOADLINK_PASSWORD")
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
            logger.info("Logging into DAT One...")
            await self.page.goto(f"{DAT_URL}/login", wait_until="networkidle", timeout=30000)
            await take_debug_screenshot(self.page, "01_login")

            await self.page.fill('input[type="email"], input[name="username"], #username', self.email)
            await self.page.fill('input[type="password"], #password', self.password)
            await self.page.click('button[type="submit"]')
            await self.page.wait_for_load_state("networkidle", timeout=20000)
            await take_debug_screenshot(self.page, "02_after_login")

            # DAT redirects to dashboard on success
            if "load-board" in self.page.url or "dashboard" in self.page.url or "loads" in self.page.url:
                self.logged_in = True
                logger.info("DAT login successful")
                return True

            # Check for user avatar/menu
            try:
                await self.page.wait_for_selector('.user-avatar, [data-testid="user-menu"], .account-menu', timeout=6000)
                self.logged_in = True
                return True
            except PWTimeout:
                pass

            logger.error(f"DAT login failed. URL: {self.page.url}")
            await take_debug_screenshot(self.page, "02_login_failed")
            return False

        except Exception as e:
            logger.error(f"DAT login error: {e}")
            return False

    async def search_alberta_loads(self) -> list[dict]:
        """Search loads originating from Alberta (province-wide search)."""
        all_loads = []
        seen_ids = set()

        try:
            await self.page.goto(f"{DAT_URL}/load-board/loads", wait_until="networkidle", timeout=20000)
            await asyncio.sleep(2)
            await take_debug_screenshot(self.page, "03_loadboard")

            # DAT search: set origin to Alberta
            try:
                # Clear and set origin field
                origin_input = await self.page.wait_for_selector(
                    '[placeholder*="Origin"], [aria-label*="Origin"], input[name="origin"]',
                    timeout=8000
                )
                await origin_input.triple_click()
                await origin_input.type("Alberta, Canada", delay=50)
                await asyncio.sleep(1)
                # Select first autocomplete suggestion
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Origin field: {e} — trying province code")
                try:
                    await self.page.fill('[placeholder*="Origin"]', "AB")
                    await asyncio.sleep(1)
                    await self.page.keyboard.press("Enter")
                except Exception:
                    pass

            # Hit search
            try:
                await self.page.click('button:has-text("Search"), button:has-text("Find Loads"), [data-testid="search-button"]')
            except Exception:
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)
            await take_debug_screenshot(self.page, "04_results")

            loads = await self._extract_dat_loads()
            for load in loads:
                if load.get("loadlink_id") not in seen_ids:
                    seen_ids.add(load["loadlink_id"])
                    all_loads.append(load)

            logger.info(f"DAT: found {len(all_loads)} Alberta loads")

        except Exception as e:
            logger.error(f"DAT search error: {e}")
            await take_debug_screenshot(self.page, "error_search")

        return all_loads

    async def _extract_dat_loads(self) -> list[dict]:
        loads = []

        try:
            await self.page.wait_for_selector(
                '[data-testid="load-row"], .load-result, tr.load, .loads-list-item',
                timeout=10000
            )
        except PWTimeout:
            logger.warning("DAT: no load rows found")
            await take_debug_screenshot(self.page, "warn_no_rows")
            return loads

        rows = await self.page.query_selector_all(
            '[data-testid="load-row"], .load-result, .loads-list-item, table tbody tr'
        )
        logger.info(f"DAT: {len(rows)} rows found")

        for row in rows:
            try:
                load = await self._parse_dat_row(row)
                if load:
                    loads.append(load)
            except Exception as e:
                logger.debug(f"DAT row parse: {e}")

        return loads

    async def _parse_dat_row(self, row) -> dict | None:
        text = await row.inner_text()
        if not text.strip():
            return None

        # Get unique ID
        load_id = await row.get_attribute("data-id") or ""
        if not load_id:
            load_id = f"dat_{hash(text[:60])}"

        # DAT typical columns: Origin | Destination | Date | Equipment | Weight | Length | Rate | Age
        cells = await row.query_selector_all("td, [class*='cell'], [class*='col']")
        cell_texts = [await c.inner_text() for c in cells]

        if len(cell_texts) < 3:
            return None

        origin_text = cell_texts[0] if len(cell_texts) > 0 else ""
        dest_text = cell_texts[1] if len(cell_texts) > 1 else ""
        date_text = cell_texts[2] if len(cell_texts) > 2 else ""
        equip_text = cell_texts[3] if len(cell_texts) > 3 else "Dry Van"
        weight_text = cell_texts[4] if len(cell_texts) > 4 else ""
        rate_text = cell_texts[5] if len(cell_texts) > 5 else ""

        origin_city, origin_prov = self._split_location(origin_text)
        dest_city, dest_prov = self._split_location(dest_text)

        if not origin_city:
            return None

        return {
            "loadlink_id": load_id,
            "source": "DAT",
            "origin_city": origin_city,
            "origin_province": origin_prov,
            "destination_city": dest_city,
            "destination_province": dest_prov,
            "equipment_type": self._clean_equipment(equip_text),
            "weight_lbs": self._parse_weight(weight_text),
            "distance_km": 0,
            "shipper_rate": self._parse_rate(rate_text),
            "pickup_date": date_text.strip(),
            "shipper_name": "",
            "raw_data": json.dumps(cell_texts),
        }

    def _split_location(self, text: str) -> tuple[str, str]:
        text = text.strip()
        # Formats: "Calgary, AB", "Calgary, AB, CA", "Calgary AB"
        parts = [p.strip() for p in text.replace(",", " ").split()]
        if len(parts) >= 2:
            # Last 2-letter uppercase part is province
            for i in range(len(parts) - 1, -1, -1):
                if len(parts[i]) == 2 and parts[i].isalpha():
                    province = parts[i].upper()
                    city = " ".join(parts[:i])
                    return city, province
        return text, "AB"

    def _clean_equipment(self, text: str) -> str:
        text = text.strip().title()
        mapping = {
            "V": "Dry Van", "Van": "Dry Van", "F": "Flatbed", "Flat": "Flatbed",
            "R": "Reefer", "Ref": "Reefer", "Sd": "Step Deck", "Step": "Step Deck",
        }
        return mapping.get(text, text or "Dry Van")

    def _parse_weight(self, text: str) -> int:
        text = text.replace(",", "").replace("lbs", "").replace("k", "000").strip()
        try:
            return int(float(text))
        except Exception:
            return 0

    def _parse_rate(self, text: str) -> float:
        text = text.replace("$", "").replace(",", "").replace("/mi", "").replace("CAD", "").strip()
        if not text or any(x in text.lower() for x in ["call", "neg", "tbd", "-", "open"]):
            return 0.0
        try:
            val = float(text)
            # DAT sometimes shows per-mile rate — if < 20 it's per mile, convert to total
            # We'll flag it but not auto-convert (distance unknown)
            return val
        except Exception:
            return 0.0

    async def stop(self):
        if self.browser:
            await self.browser.close()
