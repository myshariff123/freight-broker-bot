import json
import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BESTBUY_QUERIES = [
    "laptop", "tv 4k", "iphone", "gaming laptop", "playstation", "xbox",
    "tablet", "monitor", "camera", "dishwasher", "washer dryer",
]


async def scrape_bestbuy(client: httpx.AsyncClient, query: str) -> list[dict]:
    """BestBuy.ca JSON search API — no auth required."""
    try:
        resp = await client.get(
            "https://www.bestbuy.ca/api/2.0/json/search_prod",
            params={
                "currentRegion": "ON",
                "lang": "en-CA",
                "pageSize": 48,
                "query": query,
                "sortBy": "priceAsc",
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        products = []
        for item in resp.json().get("products", []):
            current = item.get("priceWithoutEhf") or item.get("lowCurrentPrice")
            regular = item.get("regularPrice") or item.get("highRegularPrice") or current
            if not current or not regular:
                continue
            products.append({
                "sku": f"bb_{item.get('sku', '')}",
                "name": item.get("name", "Unknown"),
                "current_price": float(current),
                "regular_price": float(regular),
                "url": f"https://www.bestbuy.ca/en-ca/{item.get('shortUrl', '')}",
                "source": "bestbuy",
            })
        return products
    except Exception as e:
        logger.warning(f"BestBuy scrape failed for '{query}': {e}")
        return []


async def scrape_walmart_search(client: httpx.AsyncClient, query: str) -> list[dict]:
    """Walmart.ca search results page scraper."""
    try:
        resp = await client.get(
            "https://www.walmart.ca/search",
            params={"q": query},
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Walmart embeds product data as __NEXT_DATA__ JSON
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
        for item in items_raw[:24]:
            price_info = item.get("priceInfo", {})
            current = price_info.get("currentPrice", {}).get("price")
            was = price_info.get("wasPrice", {}).get("price") or current
            if not current:
                continue
            products.append({
                "sku": f"wm_{item.get('usItemId', item.get('id', ''))}",
                "name": item.get("name", "Unknown"),
                "current_price": float(current),
                "regular_price": float(was),
                "url": f"https://www.walmart.ca{item.get('canonicalUrl', '')}",
                "source": "walmart",
            })
        return products
    except Exception as e:
        logger.warning(f"Walmart scrape failed for '{query}': {e}")
        return []
