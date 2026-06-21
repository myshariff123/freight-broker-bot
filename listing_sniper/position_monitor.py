import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from telegram import Bot

from listing_sniper.models import Position
from listing_sniper.seller import get_current_value_usdc, sell_token_for_usdc

logger = logging.getLogger(__name__)

TARGET_MULTIPLIER = 1.30   # sell at +30%
STOP_MULTIPLIER = 0.85     # cut at -15%
CHECK_INTERVAL = 300        # check open positions every 5 minutes
MAX_HOLD_HOURS = 72         # force-sell after 3 days regardless


async def alert(bot: Bot, msg: str):
    await bot.send_message(chat_id=os.environ["TELEGRAM_CHAT_ID"], text=msg, parse_mode="HTML")


async def check_and_close(position: Position, session: Session, bot: Bot):
    token = position.token_symbol
    buy = position.buy_usdc
    target = buy * TARGET_MULTIPLIER
    stop = buy * STOP_MULTIPLIER

    current = get_current_value_usdc(position.token_address)
    if current is None:
        logger.debug(f"Skipping {token} — quote unavailable")
        return

    if current == 0.0:
        # Token gone / no liquidity
        position.status = "failed"
        position.closed_at = datetime.now(timezone.utc)
        position.pnl_usdc = -buy
        session.commit()
        await alert(bot,
            f"💀 <b>POSITION LOST — {token}</b>\n"
            f"Token balance is zero (rug pull or no liquidity).\n"
            f"Loss: -${buy:.2f} USDC"
        )
        return

    pct = (current / buy - 1) * 100
    logger.info(f"Position check {token}: current ${current:.2f} vs buy ${buy:.2f} ({pct:+.1f}%)")

    # Check max hold time
    age_hours = (datetime.now(timezone.utc) - position.opened_at).total_seconds() / 3600
    force_sell = age_hours >= MAX_HOLD_HOURS

    should_sell = current >= target or current <= stop or force_sell
    if not should_sell:
        return

    reason = (
        "🎯 TARGET HIT (+30%)" if current >= target
        else "⛔ STOP LOSS (-15%)" if current <= stop
        else f"⏰ MAX HOLD REACHED ({age_hours:.0f}h)"
    )

    await alert(bot,
        f"{reason}\n"
        f"Token: <b>{token}</b>\n"
        f"Buy: ${buy:.2f} | Now: ${current:.2f} ({pct:+.1f}%)\n"
        f"Executing sell..."
    )

    tx_hash, _ = sell_token_for_usdc(position.token_address, min_usdc=current * 0.97)

    now = datetime.now(timezone.utc)
    position.sell_tx = tx_hash
    position.sell_usdc = current
    position.pnl_usdc = current - buy
    position.closed_at = now
    position.status = "sold" if tx_hash else "failed"
    session.commit()

    if tx_hash:
        emoji = "✅" if current >= buy else "🔴"
        await alert(bot,
            f"{emoji} <b>SELL COMPLETE — {token}</b>\n"
            f"Received: ${current:.2f} USDC\n"
            f"P&L: <b>${current - buy:+.2f}</b> ({pct:+.1f}%)\n"
            f"Tx: <code>{tx_hash}</code>"
        )
    else:
        await alert(bot,
            f"⚠️ <b>SELL FAILED — {token}</b>\n"
            f"Could not execute sell. Check wallet manually.\n"
            f"Token: <code>{position.token_address}</code>"
        )


async def monitor_positions(session_factory, bot: Bot):
    """Background task: checks all open positions every 5 minutes."""
    logger.info("Position monitor started — checking every 5 minutes")
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        session = session_factory()
        try:
            open_positions = session.query(Position).filter_by(status="open").all()
            if open_positions:
                logger.info(f"Checking {len(open_positions)} open position(s)")
            for pos in open_positions:
                try:
                    await check_and_close(pos, session, bot)
                except Exception as e:
                    logger.error(f"Position check error [{pos.token_symbol}]: {e}")
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
        finally:
            session.close()
