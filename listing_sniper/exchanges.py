import logging
import httpx

logger = logging.getLogger(__name__)

QUOTE_CURRENCIES = {"USDT", "USDC", "USD", "BTC", "ETH", "BNB", "DAI", "BUSD", "EUR", "GBP", "AUD", "TRY"}
SKIP_TOKENS = {"BTC", "ETH", "USDT", "USDC", "DAI", "BNB", "SOL", "MATIC", "DOT", "ADA", "XRP", "LTC", "BCH", "DOGE", "SHIB", "LINK", "UNI", "AAVE"}


async def get_coinbase_pairs(client: httpx.AsyncClient) -> set[str]:
    resp = await client.get("https://api.exchange.coinbase.com/products", timeout=10)
    resp.raise_for_status()
    return {p["id"] for p in resp.json() if p.get("status") == "online"}


async def get_kraken_pairs(client: httpx.AsyncClient) -> set[str]:
    resp = await client.get("https://api.kraken.com/0/public/AssetPairs", timeout=10)
    resp.raise_for_status()
    return set(resp.json().get("result", {}).keys())


async def get_bybit_pairs(client: httpx.AsyncClient) -> set[str]:
    resp = await client.get(
        "https://api.bybit.com/v5/market/instruments-info",
        params={"category": "spot", "status": "Trading", "limit": 500},
        timeout=10,
    )
    resp.raise_for_status()
    return {item["symbol"] for item in resp.json().get("result", {}).get("list", [])}


async def get_okx_pairs(client: httpx.AsyncClient) -> set[str]:
    resp = await client.get(
        "https://www.okx.com/api/v5/public/instruments",
        params={"instType": "SPOT"},
        timeout=10,
    )
    resp.raise_for_status()
    return {item["instId"] for item in resp.json().get("data", []) if item.get("state") == "live"}


def extract_base_token(pair: str) -> str:
    for sep in ["-", "/", "_"]:
        if sep in pair:
            return pair.split(sep)[0].upper()
    for quote in sorted(QUOTE_CURRENCIES, key=len, reverse=True):
        if pair.upper().endswith(quote):
            return pair[: -len(quote)].upper()
    return pair.upper()


def is_interesting(base: str) -> bool:
    return base not in SKIP_TOKENS and len(base) >= 2
