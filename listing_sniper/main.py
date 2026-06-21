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
from listing_sniper.models import Base, KnownPair, Position
from listing_sniper.position_monitor import monitor_positions

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
    return session.query(func.count(KnownPair.pair)).scalar() > 100


async def seed_baseline(session, client: httpx.AsyncClient):
    total = 0
    for exchange_name, poller in POLLERS.items():
        try:
            pairs = await poller(client)
            for pair in pairs:
                if not session.get(KnownPair, (exchange_name, pair)):
                    session.add(KnownPair(
                        exchange=exchange_name, pair=pair,
                        base_token=extract_base_token(pair),
                        first_seen=datetime.now(timezone.utc), acted=False,
                    ))
                    total += 1
            session.commit()
            logger.info(f"Seeded {exchange_name}: {len(pairs)} pairs")
        except Exception as e:
            logger.warning(f"Seed failed [{exchange_name}]: {e}")
    logger.info(f"Baseline complete — {total} pairs stored silently.")
    return total


async def handle_new_listing(exchange: str, pair: str, base: str, session, bot: Bot, client: httpx.AsyncClient, session_factory):
    logger.info(f"GENUINE NEW LISTING — {exchange.upper()}: {pair} ({base})")

    poly_addr = await find_polygon_address(base, client)

    record = KnownPair(
        exchange=exchange, pair=pair, base_token=base,
        first_seen=datetime.now(timezone.utc), polygon_addr=poly_addr, acted=False,
    )
    session.add(record)
    session.commit()

    if not poly_addr:
        await alert(bot,
            f"📋 <b>NEW LISTING — {exchange.upper()}</b>\n"
            f"Pair: <b>{pair}</b>\n"
            f"Token <b>{base}</b> not on Polygon — no auto-buy.\n"
            f"Monitor manually if interested."
        )
        return

    await alert(bot,
        f"🚨 <b>NEW CEX LISTING — {exchange.upper()}</b>\n"
        f"Pair: <b>{pair}</b> | Token: <b>{base}</b>\n"
        f"Executing ${BUY_AMOUNT_USD:.0f} USDC buy on Uniswap V3..."
    )

    tx = buy_on_polygon(poly_addr, BUY_AMOUNT_USD)
    record.tx_hash = tx
    record.acted = tx is not None
    session.commit()

    if tx:
        # Record open position for auto-sell monitor
        pos_session = session_factory()
        try:
            position = Position(
                token_address=poly_addr,
                token_symbol=base,
                exchange=exchange,
                pair=pair,
                buy_usdc=BUY_AMOUNT_USD,
                buy_tx=tx,
                status="open",
            )
            pos_session.add(position)
            pos_session.commit()
        finally:
            pos_session.close()

        await alert(bot,
            f"✅ <b>BUY EXECUTED</b> — {base}\n"
            f"Spent: ${BUY_AMOUNT_USD:.0f} USDC\n"
            f"Tx: <code>{tx}</code>\n\n"
            f"🤖 Auto-sell armed:\n"
            f"  • Sell at: +30% (${BUY_AMOUNT_USD * 1.30:.0f})\n"
            f"  • Stop loss: -15% (${BUY_AMOUNT_USD * 0.85:.0f})\n"
            f"  • Max hold: 72 hours\n"
            f"Checking every 5 minutes."
        )
    else:
        await alert(bot,
            f"⚠️ <b>AUTO-BUY FAILED</b> — {base}\n"
            f"No USDC in wallet or pool too thin.\n"
            f"If you want to buy manually: <code>{poly_addr}</code> on Uniswap V3 Polygon."
        )


async def scan_exchanges(session_factory, bot: Bot, client: httpx.AsyncClient):
    while True:
        session = session_factory()
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

                    base = extract_base_token(pair)
                    if not is_interesting(base):
                        session.add(KnownPair(exchange=exchange_name, pair=pair, base_token=base, acted=False))
                        session.commit()
                        continue

                    await handle_new_listing(exchange_name, pair, base, session, bot, client, session_factory)
                    await asyncio.sleep(3)

        except Exception as e:
            logger.error(f"Scan error: {e}")
        finally:
            session.close()

        await asyncio.sleep(POLL_INTERVAL)


async def run():
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

    async with httpx.AsyncClient() as client:
        session = Session()
        try:
            if not is_seeded(session):
                logger.info("First run — building silent baseline...")
                await alert(bot, "🔍 <b>Listing Sniper:</b> Building baseline. No alerts until complete.")
                count = await seed_baseline(session, client)
                await alert(bot,
                    f"✅ <b>Listing Sniper ACTIVE</b>\n"
                    f"Baseline: <b>{count:,} pairs</b> across 4 exchanges.\n"
                    f"You will only hear from me when a genuinely new token lists.\n"
                    f"Auto-sell armed at +30% / -15% stop."
                )
            else:
                logger.info("Already seeded — monitoring for new listings only.")
        finally:
            session.close()

    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            scan_exchanges(Session, bot, client),
            monitor_positions(Session, bot),
        )


if __name__ == "__main__":
    asyncio.run(run())
