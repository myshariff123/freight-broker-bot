import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from telegram import Bot

from odds_arb.calculator import arb_margin, find_best_odds, optimal_stakes
from odds_arb.fetcher import SPORTS, get_odds

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 6-hour interval keeps usage at ~496 requests/month on free tier (500 limit)
POLL_INTERVAL = 6 * 3600
MIN_MARGIN_PCT = 1.0    # alert only when guaranteed profit > 1% (covers slippage)
BANKROLL = 100.0        # stakes shown for a $100 bankroll — scale up/down proportionally

SPORT_EMOJI = {
    "NHL Hockey": "🏒",
    "NBA Basketball": "🏀",
    "EPL Soccer": "⚽",
    "NFL Football": "🏈",
}


async def alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


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
        f"{emoji} <b>GUARANTEED PROFIT FOUND — {sport_name}</b>",
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
        f"✅ Win either way: ${BANKROLL + profit:.2f} back on ${BANKROLL:.0f} staked",
        "⚡ <b>Place both bets within 2 minutes</b> — odds drift and the window closes.",
    ]
    return "\n".join(lines)


async def run():
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await alert(bot,
        "📊 <b>Sports Odds Arb Monitor STARTED</b>\n"
        f"Scanning NHL, NBA, EPL, NFL every 6 hours.\n"
        f"Will alert when guaranteed profit &gt; {MIN_MARGIN_PCT}%.\n"
        f"Stakes shown for $100 bankroll — scale up to your actual bet size."
    )
    logger.info("Sports Odds Arb bot started — 6-hour polling")

    async with httpx.AsyncClient() as client:
        while True:
            found = 0
            for sport_key, sport_name in SPORTS:
                events = await get_odds(client, sport_key)
                for event in events:
                    best = find_best_odds(event)
                    margin = arb_margin(best)
                    if margin and margin >= MIN_MARGIN_PCT:
                        msg = format_arb_alert(sport_name, event, best, margin)
                        await alert(bot, msg)
                        found += 1
                        logger.info(f"ARB: {event.get('away_team')} vs {event.get('home_team')} — {margin:.2f}%")
                await asyncio.sleep(2)  # small gap between sport API calls

            if found == 0:
                logger.info("Scan complete — no arb opportunities found")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
