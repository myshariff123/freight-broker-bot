import logging
import re
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

NEWEGG_CATEGORIES = [
    ("p/pl?d=laptop&N=4131&PageSize=96&Order=1", "Laptops"),
    ("p/pl?d=monitor&N=100007709&PageSize=96&Order=1", "Monitors"),
    ("p/pl?d=graphics+card&N=100007709&PageSize=96&Order=1", "GPUs"),
    ("p/pl?d=ssd&N=100007709&PageSize=96&Order=1", "SSDs"),
    ("p/pl?d=gaming+keyboard&N=100007709&PageSize=96&Order=1", "Keyboards"),
]

# CanadaComputers.com category cPaths
CANADACOMPUTERS_CATEGORIES = [
    ("43",  "Laptops"),
    ("32",  "Monitors"),
    ("585", "GPUs"),
    ("1",   "SSDs"),
    ("3",   "Desktops"),
]


async def scrape_newegg(client: httpx.AsyncClient, url_path: str) -> list[dict]:
    try:
        resp = await client.get(
            f"https://www.newegg.ca/{url_path}",
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text

        raw_items = re.findall(
            r'"ProductNumber":"([A-Z0-9]+)"[^{}]*?"UnitCost":([0-9.]+),"FinalPrice":([0-9.]+)',
            text,
        )
        soup = BeautifulSoup(text, "lxml")
        title_map: dict[str, str] = {}
        for link in soup.find_all("a", class_=re.compile(r"item-title|product-title", re.I)):
            href = link.get("href", "")
            sku_m = re.search(r"/([A-Z0-9]+)/?$", href)
            if sku_m:
                title_map[sku_m.group(1)] = link.get_text(strip=True)

        products = []
        for sku, unit_cost, final_price in raw_items:
            unit_cost_f = float(unit_cost)
            final_price_f = float(final_price)
            if final_price_f <= 0:
                continue
            products.append({
                "sku": f"newegg_{sku}",
                "name": title_map.get(sku, f"Newegg {sku}"),
                "current_price": final_price_f,
                "regular_price": max(unit_cost_f, final_price_f),
                "url": f"https://www.newegg.ca/p/{sku}",
                "source": "newegg",
            })
        return products
    except Exception as e:
        logger.warning(f"Newegg scrape failed [{url_path}]: {e}")
        return []


async def scrape_canadacomputers(client: httpx.AsyncClient, cpath: str, category_name: str) -> list[dict]:
    try:
        resp = await client.get(
            f"https://www.canadacomputers.com/index.php",
            params={"cPath": cpath},
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        products = []
        # CC uses Bootstrap grid — each product card is a col div
        items = (
            soup.select("div.product-list-item")
            or soup.select("div[class*='pq-product']")
            or soup.select("div.col-6, div.col-sm-4")
        )

        for item in items:
            # Title — try multiple selectors used across CC page versions
            title_el = (
                item.select_one("p.productTemplate_title a")
                or item.select_one(".pq-hdr-product-title a")
                or item.select_one("a[href*='pID']")
                or item.select_one("a.a-unstyled")
            )
            if not title_el:
                continue
            name = title_el.get_text(strip=True)
            if not name or len(name) < 5:
                continue

            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.canadacomputers.com/" + href.lstrip("/")
            sku_m = re.search(r"pID=(\d+)", href)
            sku = f"cc_{sku_m.group(1)}" if sku_m else f"cc_{abs(hash(name)) % 100000}"

            # Sale / current price
            sale_el = (
                item.select_one("span.pq-product-sale-price")
                or item.select_one("[class*='sale-price']")
                or item.select_one("[class*='final-price']")
                or item.select_one("[class*='pq-price']:not(del)")
            )
            # Regular / was price
            reg_el = (
                item.select_one("del.pq-product-regular-price")
                or item.select_one("del")
                or item.select_one("[class*='regular-price']")
                or item.select_one("[class*='was-price']")
            )

            if not sale_el:
                continue
            sale_text = re.sub(r"[^0-9.]", "", sale_el.get_text())
            reg_text = re.sub(r"[^0-9.]", "", reg_el.get_text()) if reg_el else ""

            try:
                current = float(sale_text) if sale_text else 0.0
                regular = float(reg_text) if reg_text else current
            except ValueError:
                continue

            if current <= 0:
                continue

            products.append({
                "sku": sku,
                "name": name[:120],
                "current_price": current,
                "regular_price": max(regular, current),
                "url": href or f"https://www.canadacomputers.com/index.php?cPath={cpath}",
                "source": "canadacomputers",
            })

        logger.debug(f"CanadaComputers [{category_name}]: {len(products)} products")
        return products

    except Exception as e:
        logger.warning(f"CanadaComputers scrape failed [cPath={cpath}]: {e}")
        return []


NEWEGG_QUERIES = NEWEGG_CATEGORIES
CANADACOMPUTERS_QUERIES = CANADACOMPUTERS_CATEGORIES
