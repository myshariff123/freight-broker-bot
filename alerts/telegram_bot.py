"""
Telegram alert system — sends opportunity alerts with Book/Skip inline buttons.
User clicks Book It → gets full contact details + tracking opens.
User clicks Skip → load marked skipped, no more alerts for it.
"""

import logging
import os
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from engine.opportunity_scorer import format_profit_tier

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Callback storage (in-memory, replaced by DB in production)
_pending_callbacks: dict[str, dict] = {}


def build_alert_message(load: dict) -> str:
    profit = load.get("estimated_profit", 0)
    tier = format_profit_tier(profit)
    posted = f"${load['shipper_rate']:,.0f}" if load.get("shipper_rate") else "NEGOTIABLE"
    carrier_mid = load.get("market_carrier_rate", 0)

    negotiable_note = ""
    if not load.get("shipper_rate"):
        target = load.get("target_ask_rate", 0)
        negotiable_note = f"\n💬 *Quote them:* ${target:,.0f} CAD"

    return (
        f"{tier} — NEW LOAD OPPORTUNITY\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Route:* {load.get('origin_city')}, {load.get('origin_province')} → "
        f"{load.get('destination_city')}, {load.get('destination_province')}\n"
        f"🚛 *Equipment:* {load.get('equipment_type', 'Dry Van')}\n"
        f"⚖️ *Weight:* {load.get('weight_lbs', 0):,} lbs\n"
        f"📅 *Pickup:* {load.get('pickup_date', 'TBD')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Shipper Rate:* {posted} CAD\n"
        f"🏭 *Est. Carrier Cost:* ~${carrier_mid:,.0f} CAD\n"
        f"✅ *Est. Profit:* *${profit:,.0f} CAD* ({load.get('margin_pct', 0):.1f}%)\n"
        f"{negotiable_note}\n"
        f"📋 *Reason:* {load.get('alert_reason', '')}\n"
        f"🏢 *Shipper:* {load.get('shipper_name', 'N/A')}\n"
        f"🔑 *Load ID:* `{load.get('loadlink_id', '')}`\n"
        f"⏰ *Found:* {datetime.now().strftime('%H:%M:%S MT')}"
    )


def build_keyboard(loadlink_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Book It — Send Me Details", callback_data=f"book:{loadlink_id}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"skip:{loadlink_id}"),
        ]
    ])


async def send_opportunity(load: dict, on_book_callback=None, on_skip_callback=None) -> int | None:
    """Send load opportunity alert. Returns Telegram message ID."""
    try:
        bot = Bot(token=BOT_TOKEN)
        message_text = build_alert_message(load)
        keyboard = build_keyboard(load["loadlink_id"])

        msg = await bot.send_message(
            chat_id=CHAT_ID,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        _pending_callbacks[load["loadlink_id"]] = {
            "load": load,
            "on_book": on_book_callback,
            "on_skip": on_skip_callback,
            "message_id": msg.message_id,
        }

        logger.info(f"Alert sent for load {load['loadlink_id']} — profit ${load.get('estimated_profit', 0):.0f}")
        return msg.message_id

    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return None


async def send_booking_details(load: dict):
    """Send full contact details after user clicks Book It."""
    bot = Bot(token=BOT_TOKEN)
    phone = load.get("shipper_phone") or "Not available — log into Loadlink"
    email = load.get("shipper_email") or "Not available — log into Loadlink"
    carrier_mid = load.get("market_carrier_rate", 0)
    carrier_high = load.get("market_carrier_rate_high", carrier_mid * 1.1)

    text = (
        f"📞 *BOOKING DETAILS — {load.get('loadlink_id')}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Shipper Contact:*\n"
        f"  Name: {load.get('shipper_name', 'N/A')}\n"
        f"  Phone: {phone}\n"
        f"  Email: {email}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Your Carrier Target:*\n"
        f"  Max pay carrier: ${carrier_high:,.0f} CAD\n"
        f"  Post on Loadlink as carrier needed: {load.get('origin_city')} → {load.get('destination_city')}\n"
        f"  Equipment: {load.get('equipment_type')}\n"
        f"  Pickup: {load.get('pickup_date')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Next Steps:*\n"
        f"1. Call/email shipper to confirm load\n"
        f"2. Post carrier need on Loadlink (or call known carriers)\n"
        f"3. Confirm carrier at or below ${carrier_high:,.0f}\n"
        f"4. Send Rate Confirmation to both parties\n"
        f"5. Reply /paid {load.get('loadlink_id')} when invoice is settled\n"
        f"\n🔗 Loadlink: https://www.loadlink.ca/en/loads/{load.get('loadlink_id')}"
    )

    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")


async def send_daily_summary(stats: dict):
    """Send end-of-day profit summary."""
    bot = Bot(token=BOT_TOKEN)
    net = stats.get("net_profit", 0)
    emoji = "🔥" if net >= 500 else "✅" if net >= 250 else "📊"

    text = (
        f"{emoji} *DAILY SUMMARY — {stats.get('date', 'Today')}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Loads Scanned: {stats.get('loads_scanned', 0):,}\n"
        f"💡 Opportunities Found: {stats.get('opportunities_found', 0)}\n"
        f"📦 Loads Booked: {stats.get('loads_booked', 0)}\n"
        f"✅ Loads Paid: {stats.get('loads_paid', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Gross Revenue: ${stats.get('gross_revenue', 0):,.0f} CAD\n"
        f"🚛 Carrier Costs: ${stats.get('carrier_costs', 0):,.0f} CAD\n"
        f"*💵 Net Profit: ${net:,.0f} CAD*\n"
        f"{'✅ GOD MODE: ON' if net >= 500 else '🎯 Target: $500/day'}"
    )

    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")


def start_callback_listener(on_book_fn, on_skip_fn):
    """Start the Telegram bot to listen for button presses."""
    app = Application.builder().token(BOT_TOKEN).build()

    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data

        if data.startswith("book:"):
            loadlink_id = data.split(":", 1)[1]
            pending = _pending_callbacks.get(loadlink_id)
            if pending:
                await query.edit_message_text(
                    f"✅ Booking in progress for load `{loadlink_id}`...",
                    parse_mode="Markdown"
                )
                await send_booking_details(pending["load"])
                if on_book_fn:
                    await on_book_fn(loadlink_id)

        elif data.startswith("skip:"):
            loadlink_id = data.split(":", 1)[1]
            await query.edit_message_text(f"⏭ Skipped load `{loadlink_id}`", parse_mode="Markdown")
            if on_skip_fn:
                await on_skip_fn(loadlink_id)

    app.add_handler(CallbackQueryHandler(callback_handler))
    return app
