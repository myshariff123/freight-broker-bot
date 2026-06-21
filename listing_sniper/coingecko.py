import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.coingecko.com/api/v3"
PLATFORM = "polygon-pos"


async def find_polygon_address(symbol: str, client: httpx.AsyncClient) -> str | None:
    """Return Polygon contract address for symbol via CoinGecko free API."""
    try:
        await asyncio.sleep(3)  # CoinGecko free tier: ~10-30 req/min
        resp = await client.get(f"{BASE}/search", params={"query": symbol}, timeout=15)
        resp.raise_for_status()
        coins = [c for c in resp.json().get("coins", []) if c.get("symbol", "").upper() == symbol.upper()]
        if not coins:
            return None

        for coin in coins[:3]:
            await asyncio.sleep(2)
            detail = await client.get(
                f"{BASE}/coins/{coin['id']}",
                params={"localization": "false", "tickers": "false", "community_data": "false", "sparkline": "false"},
                timeout=15,
            )
            detail.raise_for_status()
            data = detail.json()

            addr = (
                data.get("detail_platforms", {}).get(PLATFORM, {}).get("contract_address")
                or data.get("platforms", {}).get(PLATFORM)
            )
            if addr:
                logger.info(f"CoinGecko: {symbol} → Polygon {addr}")
                return addr

    except Exception as e:
        logger.warning(f"CoinGecko lookup failed for {symbol}: {e}")
    return None
