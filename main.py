"""
Freight Broker Bot — Freightera Quote Automation
Correct model (confirmed from portal screenshots):
  - You receive shipment needs from shippers
  - Bot submits to Freightera, gets competing carrier quotes instantly
  - Bot sends you best quotes via Telegram with your margin calculated
  - You click Book It or adjust price
  - Bot records profit

Telegram commands:
  /ltl Calgary AB → Vancouver BC | 4 pallets | 2000 lbs | Jun 20
  /ftl Calgary AB → Toronto ON | 22000 lbs | Jun 22
  /paid CALGVAN $582 $485   (record a completed deal)
  /summary                  (today's P&L)
"""

import asyncio
import logging
import os
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from freightera.quote_bot import FreighteraQuoteBot, ShipmentRequest
from freightera.quote_handler import (
    parse_quote_command, format_quote_alert, format_booking_instructions,
    calculate_shipper_price
)
from tracker.database import init_db, SessionLocal
from tracker.models import DailyStats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/bot.log"),
    ]
)
logger = logging.getLogger("main")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MARGIN_PCT = float(os.getenv("BROKER_MARGIN_PCT", "20"))

# Global quote bot instance (shared, single browser)
quote_bot: FreighteraQuoteBot = None

# Store last quotes per chat for callback handling
_last_quotes: dict[str, list] = {}
_last_requests: dict[str, ShipmentRequest] = {}


def get_or_create_stats(db, today: str) -> DailyStats:
    stats = db.query(DailyStats).filter_by(date=today).first()
    if not stats:
        stats = DailyStats(date=today)
        db.add(stats)
        db.commit()
    return stats


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚛 *Freight Broker Bot — Freightera Edition*\n\n"
        "*Commands:*\n"
        "`/ltl Calgary AB → Vancouver BC | 4 pallets | 2000 lbs | Jun 20`\n"
        "`/ftl Calgary AB → Toronto ON | 22000 lbs | Jun 22`\n"
        "`/flatbed Edmonton AB → Regina SK | 35000 lbs | Jun 25`\n"
        "`/summary` — today's P&L\n"
        "`/paid ROUTE $shipper $carrier` — record a completed deal\n\n"
        f"*Margin:* {MARGIN_PCT:.0f}% (set BROKER\\_MARGIN\\_PCT in .env)\n\n"
        "Ready. Send a shipment request to get carrier quotes.",
        parse_mode="Markdown"
    )


async def cmd_ltl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_quote(update, context, "ltl")


async def cmd_ftl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_quote(update, context, "ftl")


async def cmd_flatbed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_quote(update, context, "flatbed")


async def cmd_parcel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_quote(update, context, "parcel")


async def _handle_quote(update: Update, context: ContextTypes.DEFAULT_TYPE, freight_type: str):
    """Handle /ltl, /ftl, /flatbed commands."""
    chat_id = str(update.effective_chat.id)
    full_text = update.message.text or ""

    # Parse the request
    req = parse_quote_command(full_text)
    if not req:
        await update.message.reply_text(
            f"❌ Could not parse your request.\n\n"
            f"Format: `/{freight_type} Calgary AB → Vancouver BC | 4 pallets | 2000 lbs | Jun 20`",
            parse_mode="Markdown"
        )
        return

    req.freight_type = freight_type
    _last_requests[chat_id] = req

    # Acknowledge immediately
    ack = await update.message.reply_text(
        f"⏳ Getting {freight_type.upper()} quotes...\n"
        f"📍 {req.pickup_city} → {req.delivery_city}\n"
        f"📦 {req.num_items} {req.unit_type} | "
        f"{req.weight_per_item_lbs * req.num_items:,} lbs | {req.pickup_date}"
    )

    # Get quotes from Freightera
    try:
        if freight_type == "ltl":
            quotes = await quote_bot.get_ltl_quotes(req)
        elif freight_type == "ftl":
            quotes = await quote_bot.get_ftl_quotes(req)
        else:
            quotes = await quote_bot.get_ltl_quotes(req)

        _last_quotes[chat_id] = quotes

        # Format and send results
        message_text = format_quote_alert(req, quotes)

        # Build booking keyboard if quotes found
        keyboard = None
        if quotes:
            best = quotes[0]
            pricing = calculate_shipper_price(best.price_cad)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        f"✅ Book {best.carrier_name} (${pricing['shipper_price']:,.0f} to shipper)",
                        callback_data=f"book:0:{chat_id}"
                    )
                ],
                [
                    InlineKeyboardButton("📋 Book Quote #2", callback_data=f"book:1:{chat_id}"),
                    InlineKeyboardButton("📋 Book Quote #3", callback_data=f"book:2:{chat_id}"),
                ],
                [
                    InlineKeyboardButton("❌ Skip", callback_data=f"skip:{chat_id}"),
                ]
            ])

        await ack.delete()
        await update.message.reply_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        # Record in stats
        db = SessionLocal()
        try:
            today = date.today().isoformat()
            stats = get_or_create_stats(db, today)
            stats.opportunities_found += 1
            db.commit()
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Quote error: {e}", exc_info=True)
        await ack.edit_text(f"❌ Error getting quotes: {e}\nCheck /app/logs/bot.log for details.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("book:"):
        parts = data.split(":")
        quote_idx = int(parts[1])
        chat_id = parts[2]

        quotes = _last_quotes.get(chat_id, [])
        req = _last_requests.get(chat_id)

        if not quotes or not req or quote_idx >= len(quotes):
            await query.edit_message_text("Quote expired. Send a new request.")
            return

        selected_quote = quotes[quote_idx]
        instructions = format_booking_instructions(req, selected_quote)

        await query.edit_message_text(
            f"✅ *Booking Quote #{quote_idx + 1}*\n\n" + instructions,
            parse_mode="Markdown"
        )

        # Record booking intent
        db = SessionLocal()
        try:
            today = date.today().isoformat()
            stats = get_or_create_stats(db, today)
            stats.loads_booked += 1
            db.commit()
        finally:
            db.close()

    elif data.startswith("skip:"):
        await query.edit_message_text("⏭ Skipped.")


async def cmd_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /paid CALGVAN $582 $485
    Records a completed deal: shipper paid $582, carrier cost $485, profit $97
    """
    text = update.message.text or ""
    amounts = re.findall(r'\$?([\d,]+(?:\.\d{2})?)', text)

    if len(amounts) < 2:
        await update.message.reply_text(
            "Format: `/paid ROUTE $shipper_amount $carrier_amount`\n"
            "Example: `/paid CALGVAN $582 $485`",
            parse_mode="Markdown"
        )
        return

    shipper_amt = float(amounts[0].replace(",", ""))
    carrier_amt = float(amounts[1].replace(",", ""))
    profit = shipper_amt - carrier_amt

    db = SessionLocal()
    try:
        today = date.today().isoformat()
        stats = get_or_create_stats(db, today)
        stats.loads_paid += 1
        stats.gross_revenue += shipper_amt
        stats.carrier_costs += carrier_amt
        stats.net_profit += profit
        db.commit()

        emoji = "🔥" if stats.net_profit >= 500 else "✅"
        await update.message.reply_text(
            f"💵 *Deal Recorded*\n"
            f"Shipper paid: ${shipper_amt:,.2f} CAD\n"
            f"Carrier cost: ${carrier_amt:,.2f} CAD\n"
            f"*Your profit: ${profit:,.2f} CAD*\n\n"
            f"{emoji} Today's total: *${stats.net_profit:,.2f} CAD*"
            f"{'  — GOD MODE ✅' if stats.net_profit >= 500 else f'  — Need ${500 - stats.net_profit:.0f} more'}",
            parse_mode="Markdown"
        )
    finally:
        db.close()


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        today = date.today().isoformat()
        stats = db.query(DailyStats).filter_by(date=today).first()
        if not stats:
            await update.message.reply_text("No activity recorded today yet.")
            return

        net = stats.net_profit
        emoji = "🔥" if net >= 500 else "✅" if net > 0 else "📊"
        await update.message.reply_text(
            f"{emoji} *Summary — {today}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Quotes requested: {stats.opportunities_found}\n"
            f"Loads booked: {stats.loads_booked}\n"
            f"Loads paid: {stats.loads_paid}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Gross revenue: ${stats.gross_revenue:,.2f} CAD\n"
            f"Carrier costs: ${stats.carrier_costs:,.2f} CAD\n"
            f"*Net profit: ${net:,.2f} CAD*\n"
            f"{'🎯 GOD MODE ✅' if net >= 500 else f'Target: $500 (${500 - net:.0f} to go)'}",
            parse_mode="Markdown"
        )
    finally:
        db.close()


async def main():
    global quote_bot

    init_db()
    logger.info("DB initialized")

    # Start Freightera browser session
    quote_bot = FreighteraQuoteBot()
    await quote_bot.start()

    if not await quote_bot.login():
        logger.error("Cannot login to Freightera — check FREIGHTERA_EMAIL and FREIGHTERA_PASSWORD in .env")
        return

    logger.info("Freightera session ready")

    # Start Telegram bot
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("ltl", cmd_ltl))
    app.add_handler(CommandHandler("ftl", cmd_ftl))
    app.add_handler(CommandHandler("flatbed", cmd_flatbed))
    app.add_handler(CommandHandler("parcel", cmd_parcel))
    app.add_handler(CommandHandler("quote", cmd_ltl))  # /quote defaults to LTL
    app.add_handler(CommandHandler("paid", cmd_paid))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot started — waiting for Telegram commands")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        try:
            await asyncio.Event().wait()  # Run forever
        finally:
            await app.updater.stop()
            await app.stop()
            await quote_bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
