import hashlib
import logging
import re
from typing import Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

STRIP_TAGS = {"script", "style", "nav", "footer", "header", "aside",
              "noscript", "iframe", "form", "button"}

CONTENT_SELECTORS = [
    "main", "article", '[role="main"]', "#content", "#main-content",
    ".content-area", ".node__content", ".field-items", ".container-fluid main",
    ".wb-cont",   # Government of Canada Wet Boew theme
]


def _clean(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _extract_content(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = _clean(el)
            if len(text) > 200:
                return text
    body = soup.find("body")
    return _clean(body) if body else _clean(soup)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def fetch_and_hash(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (content_hash, content_snippet_4000chars, error_message)."""
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=30, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = _extract_content(resp.text)
            if len(content) < 100:
                return None, None, f"Content too short after extraction ({len(content)} chars)"
            return _sha256(content), content[:4000], None
    except httpx.TimeoutException:
        return None, None, "Timeout"
    except httpx.HTTPStatusError as e:
        return None, None, f"HTTP {e.response.status_code}"
    except Exception as e:
        return None, None, str(e)
