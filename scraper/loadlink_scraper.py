"""
Loadlink.ca scraper using Playwright.
Polls every 60 seconds for new loads originating in Alberta.

FIRST-TIME SETUP:
1. Run: docker exec -it freight-broker-bot python -m playwright install chromium
2. Set LOADLINK_EMAIL and LOADLINK_PASSWORD in .env
3. Set DEBUG_SCREENSHOTS=true on first run to verify selectors
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

LOADLINK_URL = "https://www.loadlink.ca"
SCREENSHOT_DIR = Path("/app/screenshots")
DEBUG = os.getenv("DEBUG_SCREENSHOTS", "false").lower() == "true"


async def take_debug_screenshot(page: Page, name: str):
    if DEBUG:
        path = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(path))
        logger.info(f"Screenshot saved: {path}")


class LoadlinkScraper:
    def __init__(self):
        self.email = os.getenv("LOADLINK_EMAIL")
        self.password = os.getenv("LOADLINK_PASSWORD")
        self.browser = None
        self.context = None
        self.page = None
        self.logged_in = False
        self.session_file = Path("/app/logs/session.json")

    async def start(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        self.page = await self.context.new_page()
        logger.info("Browser started")

    async def login(self) -> bool:
        try:
            logger.info("Navigating to Loadlink login...")
            await self.page.goto(f"{LOADLINK_URL}/en/login", wait_until="networkidle", timeout=30000)
            await take_debug_screenshot(self.page, "01_login_page")

            # Fill login form — selectors based on standard Loadlink layout
            # Adjust these if login fails (check DEBUG screenshots)
            await self.page.fill('input[type="email"], input[name="email"], #email', self.email)
            await self.page.fill('input[type="password"], input[name="password"], #password', self.password)
            await take_debug_screenshot(self.page, "02_filled_login")

            await self.page.click('button[type="submit"], input[type="submit"], .btn-login')
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            await take_debug_screenshot(self.page, "03_after_login")

            # Check if login succeeded
            if "dashboard" in self.page.url or "loads" in self.page.url or "search" in self.page.url:
                self.logged_in = True
                logger.info("Login successful")
                return True

            # Try checking for logout button as login indicator
            try:
                await self.page.wait_for_selector('a[href*="logout"], .user-menu, .nav-user', timeout=5000)
                self.logged_in = True
                logger.info("Login successful (nav detected)")
                return True
            except PWTimeout:
                pass

            logger.error(f"Login may have failed. Current URL: {self.page.url}")
            await take_debug_screenshot(self.page, "03_login_failed")
            return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            await take_debug_screenshot(self.page, "error_login")
            return False

    async def search_loads(self, origin_province: str = "AB") -> list[dict]:
        """Search for available loads from Alberta. Returns list of load dicts."""
        try:
            logger.info(f"Searching loads from {origin_province}...")

            # Navigate to load search
            await self.page.goto(f"{LOADLINK_URL}/en/loads/search", wait_until="networkidle", timeout=20000)
            await take_debug_screenshot(self.page, "04_search_page")

            # Set origin province filter to Alberta
            try:
                await self.page.select_option('select[name="origin_province"], #origin-province, [data-field="originProvince"]', origin_province)
            except Exception:
                # Try clicking province dropdown and selecting Alberta
                try:
                    await self.page.click('.origin-province, [placeholder*="Province"]')
                    await self.page.fill('.origin-province input, [placeholder*="Province"]', "Alberta")
                    await self.page.keyboard.press("Enter")
                except Exception as e:
                    logger.warning(f"Province filter failed: {e} — searching all loads")

            # Submit search
            try:
                await self.page.click('button:has-text("Search"), button:has-text("Find"), input[value="Search"]')
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_load_state("networkidle", timeout=15000)

            await take_debug_screenshot(self.page, "05_search_results")
            return await self._extract_loads()

        except Exception as e:
            logger.error(f"Search error: {e}")
            await take_debug_screenshot(self.page, "error_search")
            return []

    async def _extract_loads(self) -> list[dict]:
        """Extract load data from search results table."""
        loads = []

        try:
            # Wait for results
            await self.page.wait_for_selector(
                'table.loads-table, .load-list, .results-table, [data-testid="load-row"]',
                timeout=10000
            )
        except PWTimeout:
            logger.warning("No results table found — page may have changed structure")
            await take_debug_screenshot(self.page, "warn_no_table")
            return loads

        # Try to extract rows — Loadlink uses a table-based layout
        rows = await self.page.query_selector_all(
            'table tbody tr, .load-row, .load-item, [data-testid="load-row"]'
        )
        logger.info(f"Found {len(rows)} load rows")

        for row in rows:
            try:
                load = await self._parse_row(row)
                if load:
                    loads.append(load)
            except Exception as e:
                logger.debug(f"Row parse error: {e}")

        if not loads and rows:
            # Fallback: dump raw page text for debugging
            logger.warning("Rows found but none parsed — dumping page structure")
            await take_debug_screenshot(self.page, "debug_parse_failure")

        return loads

    async def _parse_row(self, row) -> dict | None:
        """Parse a single load row. Returns dict or None if not a valid load."""
        text = await row.inner_text()
        cells = await row.query_selector_all("td, .cell, [class*='col']")

        if len(cells) < 3:
            return None

        cell_texts = [await c.inner_text() for c in cells]

        # Attempt to get a unique load ID from the row
        load_id = await row.get_attribute("data-id") or await row.get_attribute("id") or ""
        if not load_id:
            try:
                link = await row.query_selector("a")
                href = await link.get_attribute("href") if link else ""
                load_id = href.split("/")[-1] if href else str(hash(text[:50]))
            except Exception:
                load_id = str(hash(text[:50]))

        # Parse cells — Loadlink column order (typical):
        # Origin | Destination | Equipment | Weight | Distance | Rate | Pickup Date | Broker
        # This may vary — adjust based on DEBUG screenshots
        load = {
            "loadlink_id": load_id.strip(),
            "origin_city": self._extract_city(cell_texts, 0),
            "origin_province": self._extract_province(cell_texts, 0),
            "destination_city": self._extract_city(cell_texts, 1),
            "destination_province": self._extract_province(cell_texts, 1),
            "equipment_type": cell_texts[2].strip() if len(cell_texts) > 2 else "Dry Van",
            "weight_lbs": self._parse_weight(cell_texts[3] if len(cell_texts) > 3 else ""),
            "distance_km": self._parse_distance(cell_texts[4] if len(cell_texts) > 4 else ""),
            "shipper_rate": self._parse_rate(cell_texts[5] if len(cell_texts) > 5 else ""),
            "pickup_date": cell_texts[6].strip() if len(cell_texts) > 6 else "",
            "shipper_name": cell_texts[7].strip() if len(cell_texts) > 7 else "",
            "raw_data": json.dumps(cell_texts),
        }

        # Skip if no origin/destination (likely a header row)
        if not load["origin_city"] and not load["destination_city"]:
            return None

        return load

    def _extract_city(self, cells: list, idx: int) -> str:
        if idx >= len(cells):
            return ""
        text = cells[idx].strip()
        # Format: "Calgary, AB" or "Calgary AB" or "Calgary (AB)"
        for sep in [",", "(", "/"]:
            if sep in text:
                return text.split(sep)[0].strip()
        parts = text.split()
        return " ".join(parts[:-1]) if len(parts) > 1 else text

    def _extract_province(self, cells: list, idx: int) -> str:
        if idx >= len(cells):
            return ""
        text = cells[idx].strip()
        for sep in [",", "(", "/"]:
            if sep in text:
                part = text.split(sep)[-1].strip().rstrip(")")
                if len(part) == 2 and part.isalpha():
                    return part.upper()
        parts = text.split()
        if parts and len(parts[-1]) == 2 and parts[-1].isalpha():
            return parts[-1].upper()
        return ""

    def _parse_weight(self, text: str) -> int:
        text = text.replace(",", "").replace("lbs", "").replace("kg", "").strip()
        try:
            return int(float(text))
        except Exception:
            return 0

    def _parse_distance(self, text: str) -> int:
        text = text.replace(",", "").replace("km", "").replace("mi", "").strip()
        try:
            return int(float(text))
        except Exception:
            return 0

    def _parse_rate(self, text: str) -> float:
        text = text.replace("$", "").replace(",", "").replace("CAD", "").strip()
        if not text or text.lower() in ["neg", "negotiable", "call", "tbd", "-"]:
            return 0.0
        try:
            return float(text)
        except Exception:
            return 0.0

    async def get_load_detail(self, loadlink_id: str) -> dict:
        """Navigate to a specific load page to get shipper contact info."""
        try:
            await self.page.goto(
                f"{LOADLINK_URL}/en/loads/{loadlink_id}",
                wait_until="networkidle", timeout=15000
            )
            await take_debug_screenshot(self.page, f"load_detail_{loadlink_id}")

            phone = ""
            email = ""

            try:
                phone_el = await self.page.query_selector('[class*="phone"], [data-field="phone"]')
                phone = await phone_el.inner_text() if phone_el else ""
            except Exception:
                pass

            try:
                email_el = await self.page.query_selector('[class*="email"], [data-field="email"]')
                email = await email_el.inner_text() if email_el else ""
            except Exception:
                pass

            return {"shipper_phone": phone.strip(), "shipper_email": email.strip()}
        except Exception as e:
            logger.debug(f"Detail page error for {loadlink_id}: {e}")
            return {}

    async def stop(self):
        if self.browser:
            await self.browser.close()
