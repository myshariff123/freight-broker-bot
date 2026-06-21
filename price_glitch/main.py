import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from price_glitch.models import Base, PriceBaseline, PriceRecord
from price_glitch.scraper import BESTBUY_QUERIES, scrape_bestbuy, scrape_walmart_search

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

GLITCH_THRESHOLD = 0.40  # alert when current price < 40% of baseline (60%+ off)
POLL_INTERVAL = 300       # 5 minutes between full scans
MIN_SAMPLES = 3           # need at least 3 price samples before alerting
MIN_SAVINGS = 50.0        # don't alert for small savings (< $50 CAD)
ALERTED_SKUS: set[str] = set()  # avoid spam-alerting same glitch


async def alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


def update_baseline(session, product: dict):
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    result = session.execute(
        select(
            func.avg(PriceRecord.price),
            func.min(PriceRecord.price),
            func.max(PriceRecord.price),
            func.count(PriceRecord.id),
        ).where(
            PriceRecord.sku == product["sku"],
            PriceRecord.recorded_at >= thirty_days_ago,
        )
    ).one()
    avg_p, min_p, max_p, count = result

    if avg_p is None:
        return None

    baseline = session.get(PriceBaseline, product["sku"])
    if not baseline:
        baseline = PriceBaseline(sku=product["sku"], name=product["name"],
                                  source=product["source"], url=product["url"])
        session.add(baseline)

    baseline.avg_price_30d = avg_p
    baseline.min_price_30d = min_p
    baseline.max_price_30d = max_p
    baseline.sample_count = count
    baseline.last_updated = datetime.now(timezone.utc)
    session.commit()
    return baseline


async def scan_and_alert(bot: Bot, session, client: httpx.AsyncClient):
    products = []

    for query in BESTBUY_QUERIES:
        products += await scrape_bestbuy(client, query)
        await asyncio.sleep(1)

    for query in ["laptop", "tv", "phone", "tablet"]:
        products += await scrape_walmart_search(client, query)
        await asyncio.sleep(1)

    logger.info(f"Scanned {len(products)} products")

    for product in products:
        # Record price
        record = PriceRecord(
            sku=product["sku"],
            name=product["name"],
            source=product["source"],
            url=product["url"],
            price=product["current_price"],
        )
        session.add(record)
        session.commit()

        baseline = update_baseline(session, product)
        if not baseline or baseline.sample_count < MIN_SAMPLES:
            continue

        avg = baseline.avg_price_30d
        current = product["current_price"]
        savings = avg - current

        if current < avg * GLITCH_THRESHOLD and savings >= MIN_SAVINGS:
            sku = product["sku"]
            if sku in ALERTED_SKUS:
                continue

            ALERTED_SKUS.add(sku)
            pct_off = int((1 - current / avg) * 100)

            logger.info(f"GLITCH DETECTED: {product['name']} — ${current:.2f} (avg ${avg:.2f}, {pct_off}% off)")
            await alert(bot,
                f"🔥 <b>PRICE GLITCH DETECTED</b>\n\n"
                f"<b>{product['name'][:60]}</b>\n"
                f"Source: <b>{product['source'].upper()}</b>\n\n"
                f"Current Price: <b>${current:.2f} CAD</b>\n"
                f"30-Day Average: <s>${avg:.2f}</s>\n"
                f"You Save: <b>${savings:.2f} ({pct_off}% off)</b>\n\n"
                f"<a href=\"{product['url']}\">👉 BUY NOW</a>\n\n"
                f"⚡ Act fast — usually corrected within 4-45 minutes."
            )
        else:
            # Remove from alerted set so we can re-alert if same item glitches again later
            ALERTED_SKUS.discard(product["sku"])


async def run():
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

    logger.info(f"Price Glitch Monitor started — scanning {len(BESTBUY_QUERIES)} BestBuy + Walmart categories every {POLL_INTERVAL}s")

    async with httpx.AsyncClient() as client:
        while True:
            session = Session()
            try:
                await scan_and_alert(bot, session, client)
            except Exception as e:
                logger.error(f"Scan error: {e}")
            finally:
                session.close()
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
