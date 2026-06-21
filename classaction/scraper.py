import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
}

# STRICT Canada-only filter — must explicitly mention Canada or a Canadian entity.
# Do NOT add generic US company names (Facebook, Amazon, etc.) — those are US settlements.
KEYWORDS_CANADA = [
    "canada", "canadian", "ontario", "alberta", "british columbia",
    "quebec", "saskatchewan", "manitoba", "nova scotia", "new brunswick",
    "air canada", "westjet", "flair", "swoop",
    "rogers", "bell canada", "telus", "shaw", "videotron",
    "rbc", "td bank", "scotiabank", "bmo", "cibc", "national bank",
    "tim hortons", "loblaws", "shoppers drug mart", "canadian tire",
    "petro-canada", "suncor", "enbridge",
    "cra", "canada revenue", "service canada",
    "cad", "canadian dollar",
]


async def scrape_topclassactions_canada(client: httpx.AsyncClient) -> list[dict]:
    results = []
    # Use Google AMP cache which often bypasses Cloudflare blocks on topclassactions
    for page_url in [
        "https://topclassactions.com/lawsuit-settlements/",
    ]:
        try:
            resp = await client.get(page_url, headers=HEADERS, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for article in soup.find_all("article"):
                title_el = article.find(["h2", "h3"])
                link_el = article.find("a", href=True)
                date_el = article.find("time")
                excerpt_el = article.find("p")

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                url = link_el["href"]
                if not url.startswith("http"):
                    url = "https://topclassactions.com" + url

                results.append({
                    "id": url,
                    "title": title,
                    "url": url,
                    "date": date_el.get("datetime", "") if date_el else "",
                    "excerpt": excerpt_el.get_text(strip=True)[:200] if excerpt_el else "",
                    "source": "topclassactions",
                })
        except Exception as e:
            logger.warning(f"TopClassActions scrape failed [{page_url}]: {e}")

    return results


async def scrape_classaction_org(client: httpx.AsyncClient) -> list[dict]:
    results = []
    try:
        resp = await client.get(
            "https://www.classaction.org/settlements",
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # classaction.org/settlements has h2/h3 links to individual settlement sites
        for heading in soup.find_all(["h2", "h3"]):
            link_el = heading.find("a", href=True)
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            url = link_el["href"]
            if not title or len(title) < 10:
                continue

            results.append({
                "id": url or title,
                "title": title,
                "url": url,
                "date": "",
                "excerpt": "",
                "source": "classaction_org",
            })
    except Exception as e:
        logger.warning(f"ClassAction.org scrape failed: {e}")

    return results


def is_eligible(settlement: dict) -> bool:
    """Canada-only filter — must explicitly mention Canada or a Canadian company/province."""
    text = (settlement.get("title", "") + " " + settlement.get("excerpt", "")).lower()
    return any(kw in text for kw in KEYWORDS_CANADA)
