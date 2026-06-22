import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta

import tweepy

from listing_sniper.exchanges import is_interesting

logger = logging.getLogger(__name__)

EXCHANGE_ACCOUNTS = ["coinbase", "krakenfx", "Bybit_Official", "okx", "BinanceUS"]

LISTING_KEYWORDS = [
    "listing", "now available", "now live", "trade now", "new asset",
    "now listed", "trading now", "available to trade", "spot trading",
    "new token", "now support", "starting today",
]

# Captures: $PEPE, PEPE/USDT, PEPE/USD, PEPE token
_TOKEN_RE = re.compile(
    r"\$([A-Z]{2,10})\b"
    r"|([A-Z]{3,10})/(?:USDT?|USD|BUSD|BTC|ETH)\b"
    r"|\b([A-Z]{3,10})\s+(?:token|coin|listing)\b",
    re.IGNORECASE,
)

SCAN_INTERVAL = 120  # 2 minutes — conservative to stay within rate limits


def _make_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_KEY_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        wait_on_rate_limit=True,
    )


def _extract_symbols(text: str) -> list[str]:
    symbols = set()
    for groups in _TOKEN_RE.findall(text):
        for g in groups:
            if g:
                sym = g.upper()
                if is_interesting(sym):
                    symbols.add(sym)
    return list(symbols)


def _is_listing_tweet(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in LISTING_KEYWORDS)


async def scan_twitter(session_factory, bot, http_client, handle_new_listing_fn):
    """Background task: watch official exchange Twitter accounts for listing tweets."""
    try:
        tw = _make_client()
    except Exception as e:
        logger.warning(f"Twitter scanner disabled — client init failed: {e}")
        return

    # Resolve @usernames to numeric IDs once at startup
    user_ids: dict[str, int] = {}
    for username in EXCHANGE_ACCOUNTS:
        try:
            resp = tw.get_user(username=username)
            if resp.data:
                user_ids[username] = resp.data.id
                logger.info(f"Twitter: @{username} → {resp.data.id}")
        except Exception as e:
            logger.warning(f"Twitter: could not resolve @{username}: {e}")
        await asyncio.sleep(1)

    if not user_ids:
        logger.warning("Twitter scanner: no accounts resolved — exiting")
        return

    seen: set[int] = set()
    logger.info(f"Twitter listing scanner watching {len(user_ids)} accounts every {SCAN_INTERVAL}s")

    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        window_start = datetime.now(timezone.utc) - timedelta(minutes=5)

        for username, uid in user_ids.items():
            try:
                resp = tw.get_users_tweets(
                    uid,
                    max_results=5,
                    tweet_fields=["created_at", "text"],
                    exclude=["retweets", "replies"],
                    start_time=window_start,
                )
                if not resp.data:
                    continue

                for tweet in resp.data:
                    if tweet.id in seen:
                        continue
                    seen.add(tweet.id)

                    if not _is_listing_tweet(tweet.text):
                        continue

                    symbols = _extract_symbols(tweet.text)
                    if not symbols:
                        continue

                    logger.info(
                        f"Listing tweet from @{username}: "
                        f"{tweet.text[:100]}... → symbols: {symbols}"
                    )

                    for symbol in symbols:
                        session = session_factory()
                        try:
                            await handle_new_listing_fn(
                                f"twitter_{username}",
                                f"{symbol}/USDT",
                                symbol,
                                session,
                                bot,
                                http_client,
                                session_factory,
                            )
                        except Exception as e:
                            logger.error(f"Twitter listing handler [{symbol}]: {e}")
                        finally:
                            session.close()
                        await asyncio.sleep(2)

            except Exception as e:
                logger.warning(f"Twitter scan error [@{username}]: {e}")
