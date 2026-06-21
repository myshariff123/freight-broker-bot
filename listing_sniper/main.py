import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from listing_sniper.buyer import buy_on_polygon
from listing_sniper.coingecko import find_polygon_address
from listing_sniper.exchanges import (
    extract_base_token, get_bybit_pairs, get_coinbase_pairs,
    get_kraken_pairs, get_okx_pairs, is_interesting,
)
from listing_sniper.models import Base, KnownPair

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

POLL_INTERVAL = 60
BUY_AMOUNT_USD = 50.0

POLLERS = {
    "coinbase": get_coinbase_pairs,
    "kraken": get_kraken_pairs,
    "bybit": get_bybit_pairs,
    "okx": get_okx_pairs,
}


async def alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


def is_seeded(session) -> bool:
    """Return True if the database already has baseline pairs loaded."""
    count = session.query(func.count(KnownPair.pair)).scalar()
    return count > 100  # if we have > 100 pairs, we've already seeded


async def seed_baseline(session, client: httpx.AsyncClient):
    """
    First-run: pull ALL current pairs from every exchange and store them silently.
    No alerts fired. This establishes the baseline so future NEW pairs trigger alerts.
    """
    total = 0
    for exchange_name, poller in POLLERS.items():
        try:
            pairs = await poller(client)
            for pair in pairs:
                if not session.get(KnownPair, (exchange_name, pair)):
                    base = extract_base_token(pair)
                    session.add(KnownPair(
                        exchange=exchange_name,
                        pair=pair,
                        base_token=base,
                        first_seen=datetime.now(timezone.utc),
                        acted=False,
                    ))
                    total += 1
            session.commit()
            logger.info(f"Seeded {exchange_name}: {len(pairs)} pairs")
        except Exception as e:
            logger.warning(f"Seed failed [{exchange_name}]: {e}")
    logger.info(f"Baseline complete — {total} pairs stored silently. Now monitoring for genuinely NEW listings only.")
    return total


async def handle_new_listing(exchange: str, pair: str, base: str, session, bot: Bot, client: httpx.AsyncClient):
    logger.info(f"GENUINE NEW LISTING — {exchange.upper()}: {pair} ({base})")

    poly_addr = await find_polygon_address(base, client)

    record = KnownPair(
        exchange=exchange, pair=pair, base_token=base,
        first_seen=datetime.now(timezone.utc),
        polygon_addr=poly_addr, acted=False,
    )
    session.add(record)
    session.commit()

    if not poly_addr:
        await alert(bot,
            f"📋 <b>NEW LISTING — {exchange.upper()}</b>\n"
            f"Pair: <b>{pair}</b>\n"
            f"Token <b>{base}</b> not found on Polygon — no auto-buy."
        )
        return

    await alert(bot,
        f"🚨 <b>NEW CEX LISTING — {exchange.upper()}</b>\n"
        f"Pair: <b>{pair}</b> | Token: <b>{base}</b>\n"
        f"Polygon: <code>{poly_addr}</code>\n"
        f"Executing ${BUY_AMOUNT_USD:.0f} USDC buy on Uniswap V3..."
    )

    tx = buy_on_polygon(poly_addr, BUY_AMOUNT_USD)
    record.tx_hash = tx
    record.acted = tx is not None
    session.commit()

    if tx:
        await alert(bot,
            f"✅ <b>BUY EXECUTED</b> — {base}\n"
            f"Amount: ${BUY_AMOUNT_USD:.0f} USDC\n"
            f"Tx: <code>{tx}</code>\n"
            f"🎯 Target: +30% | Cut loss: -15%"
        )
    else:
        await alert(bot,
            f"⚠️ <b>AUTO-BUY FAILED</b> — {base}\n"
            f"Reason: no USDC in wallet or pool too thin.\n"
            f"Consider manual buy: {pair} now listed on {exchange.upper()}"
        )


async def run():
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

    async with httpx.AsyncClient() as client:
        session = Session()
        try:
            if not is_seeded(session):
                logger.info("First run detected — building silent baseline (no alerts will fire during this step)...")
                await alert(bot, "🔍 <b>Listing Sniper:</b> Building baseline of all existing exchange pairs. No alerts until complete.")
                count = await seed_baseline(session, client)
                await alert(bot, f"✅ <b>Listing Sniper ACTIVE</b>\nBaseline: <b>{count:,} pairs</b> stored across Coinbase, Kraken, Bybit, OKX.\nMonitoring every 60s — you will only hear from me when a <b>genuinely new token lists</b>.")
            else:
                logger.info("Database already seeded — skipping baseline, monitoring for new listings only.")
        finally:
            session.close()

        logger.info("CEX Listing Sniper active — 60s polling, alerts only on genuinely new pairs")

        while True:
            session = Session()
            try:
                for exchange_name, poller in POLLERS.items():
                    try:
                        current_pairs = await poller(client)
                    except Exception as e:
                        logger.warning(f"Poll failed [{exchange_name}]: {e}")
                        continue

                    for pair in current_pairs:
                        if session.get(KnownPair, (exchange_name, pair)):
                            continue

                        # This pair did NOT exist when we seeded — it is a real new listing
                        base = extract_base_token(pair)
                        if not is_interesting(base):
                            # Still record it to avoid re-checking, but no alert
                            session.add(KnownPair(exchange=exchange_name, pair=pair, base_token=base, acted=False))
                            session.commit()
                            continue

                        await handle_new_listing(exchange_name, pair, base, session, bot, client)
                        await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Main loop error: {e}")
            finally:
                session.close()

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
