import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
}

KEYWORDS_ELIGIBLE = [
    "canada", "canadian", "ontario", "alberta", "british columbia",
    "data breach", "privacy", "facebook", "google", "amazon", "apple",
    "airline", "air canada", "westjet", "rogers", "bell", "telus",
    "bank", "td bank", "rbc", "scotiabank", "bmo", "cibc",
    "car", "toyota", "honda", "volkswagen", "ford",
]


async def scrape_topclassactions_canada(client: httpx.AsyncClient) -> list[dict]:
    results = []
    for page_url in [
        "https://topclassactions.com/lawsuit-settlements/canada/",
        "https://topclassactions.com/lawsuit-settlements/open-class-action-settlements/",
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
            "https://www.classaction.org/open-class-action-settlements",
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for card in soup.find_all(["article", "div"], class_=lambda c: c and any(
            kw in c.lower() for kw in ["settlement", "case", "listing", "card"]
        )):
            title_el = card.find(["h2", "h3", "h4", "a"])
            link_el = card.find("a", href=True)
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.classaction.org" + url

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
    """Rough eligibility filter — Canada-relevant or major tech/consumer brand."""
    text = (settlement.get("title", "") + " " + settlement.get("excerpt", "")).lower()
    return any(kw in text for kw in KEYWORDS_ELIGIBLE)
