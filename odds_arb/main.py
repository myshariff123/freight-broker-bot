import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from odds_arb.calculator import arb_margin, find_best_odds, optimal_stakes
from odds_arb.fetcher import SPORTS, get_odds
from odds_arb.models import ArbitrageOpportunity, Base

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 6h × 4 sports = 24 requests/day × ~31 = 744 — exceeds 500/month on daily scan
# Use 8h so 4 × 3 = 12/day × 31 = 372 requests/month
POLL_INTERVAL = 8 * 3600
MIN_MARGIN_PCT = 1.0
BANKROLL = 100.0

SPORT_EMOJI = {
    "NHL Hockey": "🏒",
    "NBA Basketball": "🏀",
    "EPL Soccer": "⚽",
    "NFL Football": "🏈",
}


async def tg_alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


def _parse_commence(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def format_arb_alert(sport_name: str, event: dict, best: dict, margin: float) -> str:
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    commence = event.get("commence_time", "")
    try:
        dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        time_str = dt.strftime("%d %b %Y %I:%M %p UTC")
    except Exception:
        time_str = commence

    emoji = SPORT_EMOJI.get(sport_name, "🎯")
    s = optimal_stakes(best, BANKROLL)
    profit = round(BANKROLL * margin / 100, 2)

    lines = [
        f"{emoji} <b>GUARANTEED PROFIT — {sport_name}</b>",
        f"<b>{away}</b> vs <b>{home}</b>",
        f"🕐 {time_str}\n",
        f"💰 <b>Profit: {margin:.2f}% = ${profit:.2f} on every $100 bet</b>\n",
        "📋 <b>Place these bets simultaneously:</b>",
    ]
    for outcome, info in s.items():
        lines.append(
            f"  • <b>{outcome[:30]}</b>\n"
            f"    Stake: <b>${info['stake']:.2f}</b> @ {info['odds']:.3f} odds\n"
            f"    Book: <i>{info['book']}</i>  |  Payout: ${info['payout']:.2f}"
        )
    lines += [
        "",
        f"✅ Guaranteed return: ${BANKROLL + profit:.2f} on ${BANKROLL:.0f} staked",
        "⚡ <b>Place both bets within 2 minutes — odds drift fast.</b>",
    ]
    return "\n".join(lines)


async def run():
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await tg_alert(bot,
        "📊 <b>Sports Odds Arb Monitor STARTED</b>\n"
        f"Scanning NHL, NBA, EPL, NFL every 8 hours.\n"
        f"Alerts when guaranteed profit &gt; {MIN_MARGIN_PCT}%.\n"
        f"Stakes shown for $100 bankroll."
    )
    logger.info("Sports Odds Arb bot started — 8h polling")

    async with httpx.AsyncClient() as client:
        while True:
            found = 0
            for sport_key, sport_name in SPORTS:
                events = await get_odds(client, sport_key)
                for event in events:
                    best = find_best_odds(event)
                    margin = arb_margin(best)
                    if margin and margin >= MIN_MARGIN_PCT:
                        s = optimal_stakes(best, BANKROLL)
                        # Persist to DB
                        session = Session()
                        try:
                            opp = ArbitrageOpportunity(
                                sport=sport_name,
                                home_team=event.get("home_team", ""),
                                away_team=event.get("away_team", ""),
                                commence_time=_parse_commence(event.get("commence_time", "")),
                                margin_pct=margin,
                                stakes_json=json.dumps(s),
                            )
                            session.add(opp)
                            session.commit()
                        except Exception as e:
                            logger.error(f"DB save error: {e}")
                            session.rollback()
                        finally:
                            session.close()

                        msg = format_arb_alert(sport_name, event, best, margin)
                        await tg_alert(bot, msg)
                        found += 1
                        logger.info(f"ARB: {event.get('away_team')} vs {event.get('home_team')} — {margin:.2f}%")

                # Store API quota remaining for dashboard
                await asyncio.sleep(2)

            if found == 0:
                logger.info("Scan complete — no arb opportunities found")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
