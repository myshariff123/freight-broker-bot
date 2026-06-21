import json
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
    # (url_path, category_name)
    ("p/pl?d=laptop&N=4131&PageSize=96&Order=1", "Laptops"),
    ("p/pl?d=monitor&N=100007709&PageSize=96&Order=1", "Monitors"),
    ("p/pl?d=graphics+card&N=100007709&PageSize=96&Order=1", "GPUs"),
    ("p/pl?d=ssd&N=100007709&PageSize=96&Order=1", "SSDs"),
    ("p/pl?d=gaming+keyboard&N=100007709&PageSize=96&Order=1", "Keyboards"),
]


async def scrape_newegg(client: httpx.AsyncClient, url_path: str) -> list[dict]:
    """Scrape Newegg.ca using their embedded JSON product data."""
    try:
        resp = await client.get(
            f"https://www.newegg.ca/{url_path}",
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text

        # Newegg embeds product data as window.App.Items or similar patterns
        # Each product item has ItemCell.FinalPrice and UnitCost
        product_data_str = re.search(
            r'"ProductNumber":"([A-Z0-9]+)"[^{}]*?"FinalPrice":([0-9.]+)[^{}]*?"Title":"([^"]+)"',
            text,
        )

        # Extract all product records via broader regex
        raw_items = re.findall(
            r'"ProductNumber":"([A-Z0-9]+)"[^{}]*?"UnitCost":([0-9.]+),"FinalPrice":([0-9.]+)',
            text,
        )

        # Also get titles by parsing the page structure
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


async def scrape_walmart_search(client: httpx.AsyncClient, query: str) -> list[dict]:
    """Walmart.ca search results via __NEXT_DATA__ JSON."""
    try:
        resp = await client.get(
            "https://www.walmart.ca/search",
            params={"q": query},
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return []

        data = json.loads(script.string)
        items_raw = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("searchResult", {})
            .get("itemStacks", [{}])[0]
            .get("items", [])
        )

        products = []
        for item in items_raw[:48]:
            price_info = item.get("priceInfo", {})
            current = price_info.get("currentPrice", {}).get("price")
            was = price_info.get("wasPrice", {}).get("price") or current
            if not current:
                continue
            products.append({
                "sku": f"wm_{item.get('usItemId', item.get('id', ''))}",
                "name": item.get("name", "Unknown")[:120],
                "current_price": float(current),
                "regular_price": float(was),
                "url": f"https://www.walmart.ca{item.get('canonicalUrl', '')}",
                "source": "walmart",
            })
        return products

    except Exception as e:
        logger.warning(f"Walmart scrape failed for '{query}': {e}")
        return []


NEWEGG_QUERIES = NEWEGG_CATEGORIES
WALMART_QUERIES = ["laptop", "tv 4k", "iphone", "tablet", "gaming console"]
