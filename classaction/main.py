import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from classaction.models import Base, Settlement
from classaction.scraper import is_eligible, scrape_classaction_org, scrape_topclassactions_canada

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CHECK_INTERVAL = 24 * 3600  # once per day is plenty for settlement updates


async def alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


async def check_settlements(bot: Bot, session, client: httpx.AsyncClient):
    all_results = []
    all_results += await scrape_topclassactions_canada(client)
    all_results += await scrape_classaction_org(client)

    logger.info(f"Found {len(all_results)} settlements total")

    new_count = 0
    for s in all_results:
        if not s.get("id") or not s.get("title"):
            continue

        existing = session.get(Settlement, s["id"])
        if existing:
            continue

        record = Settlement(
            id=s["id"],
            title=s["title"],
            url=s["url"],
            source=s["source"],
            excerpt=s.get("excerpt", ""),
            date_posted=s.get("date", ""),
            alerted=False,
        )
        session.add(record)
        session.commit()
        new_count += 1

        if is_eligible(s):
            record.alerted = True
            session.commit()

            await alert(bot,
                f"⚖️ <b>NEW CLASS ACTION SETTLEMENT</b>\n\n"
                f"<b>{s['title'][:80]}</b>\n"
                f"Source: {s['source'].upper()}\n"
                f"{s.get('excerpt', '')[:200]}\n\n"
                f"<a href=\"{s['url']}\">📋 View & File Claim →</a>\n\n"
                f"Action: Check eligibility, file before deadline. Takes ~5 minutes."
            )
            logger.info(f"Alerted: {s['title'][:60]}")

    logger.info(f"New settlements this cycle: {new_count}")


async def run():
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

    await alert(bot, "⚖️ <b>Class Action Tracker STARTED</b>\nMonitoring TopClassActions.com + ClassAction.org every 6 hours for eligible Canadian settlements.")

    logger.info("Class Action Settlement Tracker started")

    async with httpx.AsyncClient() as client:
        while True:
            session = Session()
            try:
                await check_settlements(bot, session, client)
            except Exception as e:
                logger.error(f"Check error: {e}")
            finally:
                session.close()
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
