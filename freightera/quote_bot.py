"""
Freightera Quote Bot — submits shipment requests and extracts carrier quotes.
Based on actual portal screenshots (Jun 2026).

Flow:
  1. Login to freightera.com
  2. Navigate to /shippers/quote-ltl or /shippers/quote-ftl
  3. Fill form with shipment details
  4. Click GET QUOTES
  5. Extract all carrier quotes from results page
  6. Return ranked list with prices, transit times, carrier names
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

BASE_URL = "https://www.freightera.com"
SCREENSHOT_DIR = Path("/app/screenshots")
DEBUG = os.getenv("DEBUG_SCREENSHOTS", "false").lower() == "true"

LOCATION_TYPES = [
    "Business with Dock or Forklift",
    "Business without Dock",
    "Residential",
    "Construction Site",
    "Limited Access",
    "Tradeshow",
]


@dataclass
class ShipmentRequest:
    pickup_city: str           # "Calgary, AB" or postal code "T2P 0C9"
    delivery_city: str         # "Vancouver, BC" or "V6C 1T2"
    pickup_date: str           # "2026-06-20"
    freight_type: str          # "ltl" | "ftl" | "flatbed" | "parcel" | "container"
    num_items: int = 1
    unit_type: str = "Pallets" # Pallets, Skids, Boxes, Crates
    weight_per_item_lbs: int = 500
    length_in: int = 48
    width_in: int = 40
    height_in: int = 48
    description: str = "General Freight"
    pickup_location_type: str = "Business with Dock or Forklift"
    delivery_location_type: str = "Business with Dock or Forklift"
    temperature_control: str = "None (Not Required)"


@dataclass
class CarrierQuote:
    carrier_name: str
    price_cad: float
    transit_days: str
    service_type: str
    quote_id: str = ""
    rank: int = 0


class FreighteraQuoteBot:
    def __init__(self):
        self.email = os.getenv("FREIGHTERA_EMAIL")
        self.password = os.getenv("FREIGHTERA_PASSWORD")
        self.browser = None
        self.context = None
        self.page = None
        self.logged_in = False

    async def start(self):
        playwright = await async_playwright().start()
        self._playwright = playwright
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        self.page = await self.context.new_page()
        logger.info("Browser started")

    async def _screenshot(self, name: str):
        if DEBUG:
            path = SCREENSHOT_DIR / f"ft_{name}_{datetime.now().strftime('%H%M%S')}.png"
            await self.page.screenshot(path=str(path))

    async def login(self) -> bool:
        try:
            logger.info("Logging into Freightera...")
            await self.page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
            await self._screenshot("01_login")

            # Dismiss cookie consent banner if present
            try:
                await self.page.click('button:has-text("Got It"), button:has-text("Accept"), #cookie-accept', timeout=4000)
                await asyncio.sleep(0.5)
                logger.info("Cookie banner dismissed")
            except PWTimeout:
                pass  # No banner, continue

            # Fill email — placeholder is "Email"
            await self.page.fill('input[placeholder="Email"]', self.email)
            await asyncio.sleep(0.3)

            # Fill password — placeholder is "Password"
            await self.page.fill('input[placeholder="Password"]', self.password)
            await asyncio.sleep(0.3)

            await self._screenshot("01b_filled")

            # Click the green LOG IN button (text is uppercase "LOG IN")
            await self.page.click('button:has-text("LOG IN")', timeout=10000)
            await self.page.wait_for_load_state("networkidle", timeout=20000)
            await self._screenshot("02_after_login")

            if "login" not in self.page.url.lower():
                self.logged_in = True
                logger.info(f"Freightera login successful — URL: {self.page.url}")
                return True

            logger.error(f"Login failed — still on login page. URL: {self.page.url}")
            await self._screenshot("02_login_failed")
            return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            await self._screenshot("error_login")
            return False

    async def get_ltl_quotes(self, req: ShipmentRequest) -> list[CarrierQuote]:
        """Submit LTL quote request and return all carrier quotes."""
        return await self._get_quotes(req, "ltl")

    async def get_ftl_quotes(self, req: ShipmentRequest) -> list[CarrierQuote]:
        """Submit FTL quote request and return all carrier quotes."""
        return await self._get_quotes(req, "ftl")

    async def _get_quotes(self, req: ShipmentRequest, freight_type: str) -> list[CarrierQuote]:
        if not self.logged_in:
            if not await self.login():
                return []

        url_map = {
            "ltl": f"{BASE_URL}/shippers/quote-ltl",
            "ftl": f"{BASE_URL}/shippers/quote-ftl",
            "flatbed": f"{BASE_URL}/shippers/quote-flatbed",
            "parcel": f"{BASE_URL}/shippers/quote-parcel",
            "container": f"{BASE_URL}/shippers/quote-container",
        }

        url = url_map.get(freight_type, url_map["ltl"])
        logger.info(f"Navigating to {url}")

        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(1)
        await self._screenshot(f"03_{freight_type}_form")

        try:
            if freight_type == "ltl":
                await self._fill_ltl_form(req)
            elif freight_type == "ftl":
                await self._fill_ftl_form(req)
            else:
                await self._fill_ltl_form(req)

            await self._screenshot(f"04_{freight_type}_filled")

            # Scroll GET QUOTES button into view and click it
            get_quotes_btn = await self.page.query_selector(
                'button:has-text("GET QUOTES"), button:has-text("Get Quotes"), .get-quotes-btn'
            )
            if not get_quotes_btn:
                logger.error("GET QUOTES button not found on page")
                await self._screenshot(f"error_no_button_{freight_type}")
                return []
            await get_quotes_btn.scroll_into_view_if_needed()
            await self._screenshot(f"04b_{freight_type}_before_submit")
            await get_quotes_btn.click()
            logger.info("Submitted quote request, waiting for results...")

            # Brief pause to let the page start navigating / loading
            await asyncio.sleep(3)
            await self._screenshot(f"05_{freight_type}_results")

            quotes = await self._extract_quotes()
            logger.info(f"Extracted {len(quotes)} carrier quotes")
            return quotes

        except Exception as e:
            logger.error(f"Quote submission error: {e}", exc_info=True)
            await self._screenshot(f"error_{freight_type}")
            return []

    async def _fill_ltl_form(self, req: ShipmentRequest):
        """Fill the LTL quote form based on actual form fields seen in screenshots."""

        # --- Pickup Location ---
        pickup_inputs = await self.page.query_selector_all(
            'input[placeholder="Zip/Postal Code or City"]'
        )
        if len(pickup_inputs) >= 1:
            await pickup_inputs[0].click()
            await pickup_inputs[0].fill(req.pickup_city)
            await asyncio.sleep(0.8)
            # Select first autocomplete result
            try:
                await self.page.wait_for_selector(
                    '.autocomplete-result, .pac-item, [class*="suggestion"], li[role="option"]',
                    timeout=3000
                )
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")
            except PWTimeout:
                await self.page.keyboard.press("Enter")

        # --- Delivery Location ---
        if len(pickup_inputs) >= 2:
            await pickup_inputs[1].click()
            await pickup_inputs[1].fill(req.delivery_city)
            await asyncio.sleep(0.8)
            try:
                await self.page.wait_for_selector(
                    '.autocomplete-result, .pac-item, [class*="suggestion"], li[role="option"]',
                    timeout=3000
                )
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")
            except PWTimeout:
                await self.page.keyboard.press("Enter")

        await asyncio.sleep(0.5)

        # --- Location Types ---
        selects = await self.page.query_selector_all('select')
        location_type_selects = []
        for sel in selects:
            inner = await sel.inner_text()
            if "Business" in inner or "Residential" in inner or "Dock" in inner:
                location_type_selects.append(sel)

        for sel in location_type_selects[:2]:
            try:
                await sel.select_option(label=req.pickup_location_type)
            except Exception:
                try:
                    await sel.select_option(index=0)
                except Exception:
                    pass

        # --- Pickup Date ---
        date_input = await self.page.query_selector(
            'input[type="text"][placeholder*="date"], input.datepicker, [class*="date-picker"] input'
        )
        if date_input:
            await date_input.click(click_count=3)
            await date_input.type(req.pickup_date, delay=50)
            await self.page.keyboard.press("Escape")  # Close calendar
        else:
            try:
                cal_icon = await self.page.query_selector('[class*="calendar"], .fa-calendar')
                if cal_icon:
                    await cal_icon.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        await asyncio.sleep(0.3)

        # --- Description of Goods ---
        desc_input = await self.page.query_selector('input[placeholder="Description of Goods"]')
        if desc_input:
            await desc_input.fill(req.description)

        # --- Number of Items ---
        num_input = await self.page.query_selector('input[placeholder="#"]')
        if num_input:
            await num_input.click(click_count=3)
            await num_input.type(str(req.num_items))

        # --- Unit Type (Pallets) ---
        unit_selects = await self.page.query_selector_all('select')
        for sel in unit_selects:
            try:
                inner = await sel.inner_text()
                if "Pallets" in inner or "Skids" in inner or "Boxes" in inner:
                    await sel.select_option(label=req.unit_type)
                    break
            except Exception:
                pass

        # --- Dimensions (L x W x H) ---
        dim_inputs = await self.page.query_selector_all(
            'input[placeholder="L"], input[placeholder="W"], input[placeholder="H"]'
        )
        dims = [req.length_in, req.width_in, req.height_in]
        for i, inp in enumerate(dim_inputs[:3]):
            await inp.click(click_count=3)
            await inp.type(str(dims[i]))

        # --- Weight per item ---
        # "LB" is a toggle badge next to the input, not the input's placeholder.
        # Use JS to find the input whose sibling/parent contains the "LB" text.
        weight_result = await self.page.evaluate("""
            (w) => {
                let el = document.querySelector('input[name*="weight" i], input[id*="weight" i]');
                if (!el) {
                    for (const inp of document.querySelectorAll('input')) {
                        const sib = inp.nextElementSibling;
                        const par = inp.parentElement;
                        const sibText = sib ? sib.textContent.trim() : '';
                        const parText = par ? par.textContent.trim() : '';
                        if (sibText === 'LB' || sibText === 'KG' ||
                            (/^\\d*\\s*LB/i.test(parText) && parText.length < 30)) {
                            el = inp;
                            break;
                        }
                    }
                }
                if (!el) return 'NOT_FOUND';
                el.value = '';
                el.focus();
                el.value = String(w);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.blur();
                return el.value;
            }
        """, req.weight_per_item_lbs)
        logger.info(f"Weight field fill result: {weight_result}")

        # --- Temperature Control ---
        for sel in await self.page.query_selector_all('select'):
            try:
                inner = await sel.inner_text()
                if "Temperature" in inner or "Not Required" in inner or "Reefer" in inner:
                    await sel.select_option(label=req.temperature_control)
                    break
            except Exception:
                pass

        await asyncio.sleep(0.5)

    async def _fill_ftl_form(self, req: ShipmentRequest):
        """Fill FTL quote form."""

        pickup_inputs = await self.page.query_selector_all(
            'input[placeholder="Zip/Postal Code or City"]'
        )
        if len(pickup_inputs) >= 1:
            await pickup_inputs[0].fill(req.pickup_city)
            await asyncio.sleep(0.8)
            await self.page.keyboard.press("ArrowDown")
            await self.page.keyboard.press("Enter")

        if len(pickup_inputs) >= 2:
            await pickup_inputs[1].fill(req.delivery_city)
            await asyncio.sleep(0.8)
            await self.page.keyboard.press("ArrowDown")
            await self.page.keyboard.press("Enter")

        # Location types
        for sel in await self.page.query_selector_all('select'):
            try:
                inner = await sel.inner_text()
                if "Business" in inner or "Dock" in inner:
                    await sel.select_option(label=req.pickup_location_type)
            except Exception:
                pass

        # Pickup date
        date_input = await self.page.query_selector('input[class*="date"], [class*="datepicker"] input')
        if date_input:
            await date_input.click(click_count=3)
            await date_input.type(req.pickup_date, delay=50)

        # Description
        desc = await self.page.query_selector('input[placeholder="Description of Goods"], textarea[placeholder*="Description"]')
        if desc:
            await desc.fill(req.description)

        # Weight / items
        num_input = await self.page.query_selector('input[placeholder="#"]')
        if num_input:
            await num_input.click(click_count=3)
            await num_input.type(str(req.num_items))

        weight_result = await self.page.evaluate("""
            (w) => {
                let el = document.querySelector('input[name*="weight" i], input[id*="weight" i]');
                if (!el) {
                    for (const inp of document.querySelectorAll('input')) {
                        const sib = inp.nextElementSibling;
                        if (sib && (sib.textContent.trim() === 'LB' || sib.textContent.trim() === 'KG')) {
                            el = inp; break;
                        }
                    }
                }
                if (!el) return 'NOT_FOUND';
                el.value = String(w);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return el.value;
            }
        """, req.weight_per_item_lbs * req.num_items)
        logger.info(f"FTL weight fill result: {weight_result}")

        await asyncio.sleep(0.5)

    async def _extract_quotes(self) -> list[CarrierQuote]:
        """Extract carrier quotes from the Select Your Quote results page.

        Freightera lazy-loads cards after networkidle. We wait until CAD prices
        appear in the DOM, then use SELECT buttons as anchors to locate each card.
        """
        quotes = []

        # Quotes load asynchronously — wait for any CAD price to appear in the page
        try:
            await self.page.wait_for_function(
                "() => document.body.innerText.includes('CAD')",
                timeout=25000,
                polling=500,
            )
            await asyncio.sleep(2)  # Let remaining cards finish rendering
        except PWTimeout:
            logger.warning("No CAD prices appeared within 25s")
            await self._screenshot("warn_no_quotes")
            return quotes

        await self._screenshot("06_quotes_loaded")

        # Use SELECT buttons as anchors: walk up the DOM until we find the card
        # containing a CAD price, then extract its text.
        raw_cards = await self.page.evaluate(r"""
            () => {
                const results = [];
                document.querySelectorAll('button, a').forEach(btn => {
                    if (!btn.textContent.trim().includes('SELECT')) return;
                    let node = btn;
                    for (let i = 0; i < 8; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const text = node.innerText || '';
                        if (/\$[\d,]+\.\d{2}\s*CAD/.test(text)) {
                            results.push(text.substring(0, 600));
                            break;
                        }
                    }
                });
                return results;
            }
        """)

        logger.info(f"Raw quote cards found: {len(raw_cards)}")

        for i, text in enumerate(raw_cards):
            try:
                price_match = re.search(r'\$([\d,]+\.\d{2})\s*CAD', text)
                if not price_match:
                    continue
                price = float(price_match.group(1).replace(',', ''))
                if price < 10:
                    continue

                # Delivery range e.g. "JUN 18 - JUN 22"
                delivery_match = re.search(
                    r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d+'
                    r'\s*[-–]\s*'
                    r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d+',
                    text, re.I
                )
                delivery = delivery_match.group(0).upper() if delivery_match else "TBD"

                rate_match = re.search(r'Rate\s*\d+', text, re.I)
                carrier = rate_match.group(0) if rate_match else f"Rate {i + 1}"

                service = "Standard"
                if re.search(r'express|next.?day|overnight|priority', text, re.I):
                    service = "Express"
                elif re.search(r'economy|ground|saver', text, re.I):
                    service = "Economy"

                quotes.append(CarrierQuote(
                    carrier_name=carrier,
                    price_cad=price,
                    transit_days=delivery,
                    service_type=service,
                    rank=i + 1,
                ))
            except Exception as e:
                logger.debug(f"Quote parse error at index {i}: {e}")

        quotes.sort(key=lambda q: q.price_cad)
        for i, q in enumerate(quotes):
            q.rank = i + 1

        return quotes

    async def stop(self):
        if self.browser:
            await self.browser.close()
