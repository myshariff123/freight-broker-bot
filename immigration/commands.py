import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes

from .models import ImmSubscriber, ImmChange, ImmSource

logger = logging.getLogger(__name__)

IMPACT_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
IMPACT_EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📋", "LOW": "ℹ️"}

PROVINCE_NAMES = {
    "ON": "Ontario", "BC": "British Columbia", "AB": "Alberta",
    "SK": "Saskatchewan", "MB": "Manitoba", "NS": "Nova Scotia",
    "NB": "New Brunswick", "PE": "Prince Edward Island", "NL": "Newfoundland & Labrador",
    "NT": "Northwest Territories", "YT": "Yukon", "QC": "Quebec", "NU": "Nunavut",
}


def _get_or_create(session: Session, chat_id: int, username: str = None) -> ImmSubscriber:
    sub = session.query(ImmSubscriber).filter_by(telegram_chat_id=chat_id).first()
    if not sub:
        sub = ImmSubscriber(
            telegram_chat_id=chat_id,
            telegram_username=username,
            province_filters=[],
            case_type_filters=[],
            alert_level_minimum="MEDIUM",
            is_active=True,
        )
        session.add(sub)
        session.commit()
    return sub


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id, update.effective_user.username)
    sub.is_active = True
    session.commit()
    session.close()
    await update.message.reply_text(
        "🍁 *Welcome to ImmAlert Canada*\n\n"
        "You now receive real-time alerts when Canadian immigration policy changes, covering:\n\n"
        "🏛️ *Federal:* IRCC notices, Express Entry draws, processing times, TFW, IMP, family sponsorship, "
        "study permits, citizenship\n\n"
        "🗺️ *All 12 Provincial Nominee Programs:* ON, BC, AB, SK, MB, NS, NB, PE, NL, NT, YT, QC\n\n"
        "🔬 *Special Programs:* Atlantic, Rural & Northern, Agri-Food, Start-Up Visa, Caregivers\n\n"
        "Each alert includes:\n"
        "• Impact level (CRITICAL / HIGH / MEDIUM / LOW)\n"
        "• Which case types are affected\n"
        "• What your clients need to know\n"
        "• Immediate actions you should take\n\n"
        "*Commands:*\n"
        "/email your@email.com — Add email delivery\n"
        "/provinces ON BC AB — Filter to provinces you care about\n"
        "/level HIGH — Set minimum alert level\n"
        "/summary — Today's changes\n"
        "/history 7 — Last N days of changes\n"
        "/status — Your current settings\n"
        "/pause /resume /stop — Manage subscription\n\n"
        "Alerts arrive within 15 minutes of any detected change.",
        parse_mode="Markdown",
    )


async def cmd_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    if not context.args:
        current = sub.email or "Not set"
        await update.message.reply_text(
            f"Current email: {current}\n\nUsage: /email your@address.com"
        )
        session.close()
        return
    email = context.args[0].strip().lower()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email address.")
        session.close()
        return
    sub.email = email
    session.commit()
    session.close()
    await update.message.reply_text(f"✅ Email alerts enabled → {email}")


async def cmd_provinces(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    if not context.args:
        cur = sub.province_filters or []
        if cur:
            names = ", ".join(PROVINCE_NAMES.get(p, p) for p in cur)
            txt = (f"Filtering to: {names}\n\n"
                   "Use /provinces ALL to monitor all, or /provinces ON BC to change.")
        else:
            txt = "Monitoring ALL provinces.\n\nUse /provinces ON BC AB to filter."
        await update.message.reply_text(txt)
        session.close()
        return
    if context.args[0].upper() == "ALL":
        sub.province_filters = []
        session.commit()
        await update.message.reply_text("✅ Monitoring all provinces.")
    else:
        valid = [a.upper() for a in context.args if a.upper() in PROVINCE_NAMES]
        invalid = [a for a in context.args if a.upper() not in PROVINCE_NAMES]
        sub.province_filters = valid
        session.commit()
        names = ", ".join(PROVINCE_NAMES.get(p, p) for p in valid)
        txt = f"✅ Now filtering to: {names}"
        if invalid:
            txt += f"\n❓ Unknown codes skipped: {', '.join(invalid)}"
        await update.message.reply_text(txt)
    session.close()


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    if not context.args or context.args[0].upper() not in levels:
        await update.message.reply_text(
            f"Current minimum: *{sub.alert_level_minimum}*\n\n"
            "Set with: /level LOW | MEDIUM | HIGH | CRITICAL\n\n"
            "• *LOW* — Every change including minor website updates\n"
            "• *MEDIUM* — Processing time changes, form updates _(recommended)_\n"
            "• *HIGH* — Stream openings/closings, CRS/score changes\n"
            "• *CRITICAL* — Program suspensions and emergency deadlines only",
            parse_mode="Markdown",
        )
        session.close()
        return
    sub.alert_level_minimum = context.args[0].upper()
    session.commit()
    session.close()
    await update.message.reply_text(f"✅ Minimum alert level: {sub.alert_level_minimum}")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    since = datetime.utcnow() - timedelta(hours=24)
    changes = (
        session.query(ImmChange, ImmSource)
        .join(ImmSource, ImmChange.source_id == ImmSource.id)
        .filter(ImmChange.detected_at >= since)
        .order_by(ImmChange.detected_at.desc())
        .limit(10)
        .all()
    )
    if not changes:
        await update.message.reply_text("No immigration policy changes detected in the last 24 hours.")
        session.close()
        return
    msg = f"📊 *Last 24 Hours — {len(changes)} Change(s) Detected*\n\n"
    for change, source in changes:
        a = change.analysis or {}
        ie = IMPACT_EMOJI.get(change.impact_level, "📋")
        dt = change.detected_at.strftime("%H:%M UTC")
        summary = a.get("summary", "")[:120]
        msg += f"{ie} `{dt}` *{change.impact_level}* — {source.name}\n_{summary}_\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    session.close()


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = 7
    if context.args:
        try:
            days = max(1, min(int(context.args[0]), 30))
        except ValueError:
            pass
    sf = context.bot_data["db_session"]
    session: Session = sf()
    since = datetime.utcnow() - timedelta(days=days)
    changes = (
        session.query(ImmChange, ImmSource)
        .join(ImmSource, ImmChange.source_id == ImmSource.id)
        .filter(ImmChange.detected_at >= since)
        .order_by(ImmChange.detected_at.desc())
        .limit(25)
        .all()
    )
    if not changes:
        await update.message.reply_text(f"No changes recorded in the last {days} days.")
        session.close()
        return
    msg = f"📅 *Last {days} Days — {len(changes)} Change(s)*\n\n"
    for change, source in changes:
        ie = IMPACT_EMOJI.get(change.impact_level, "📋")
        dt = change.detected_at.strftime("%b %d %H:%M")
        msg += f"{ie} `{dt}` — {source.name} _{change.impact_level}_\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    session.close()


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    provinces = ", ".join(sub.province_filters) if sub.province_filters else "ALL"
    email_str = sub.email or "Not set — use /email"
    last = sub.last_alert_at.strftime("%Y-%m-%d %H:%M UTC") if sub.last_alert_at else "None yet"
    status = "✅ Active" if sub.is_active else "⏸️ Paused"
    since = sub.subscribed_at.strftime("%Y-%m-%d") if sub.subscribed_at else "Unknown"
    await update.message.reply_text(
        f"*Your ImmAlert Settings*\n\n"
        f"Status: {status}\n"
        f"Email: {email_str}\n"
        f"Provinces: {provinces}\n"
        f"Min. Alert Level: {sub.alert_level_minimum}\n"
        f"Last Alert: {last}\n"
        f"Subscribed Since: {since}",
        parse_mode="Markdown",
    )
    session.close()


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    sub.is_active = False
    session.commit()
    session.close()
    await update.message.reply_text("⏸️ Alerts paused. Use /resume to reactivate.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    sub.is_active = True
    session.commit()
    session.close()
    await update.message.reply_text("✅ Alerts resumed.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sf = context.bot_data["db_session"]
    session: Session = sf()
    sub = _get_or_create(session, update.effective_chat.id)
    sub.is_active = False
    session.commit()
    session.close()
    await update.message.reply_text(
        "❌ Unsubscribed. Your history is preserved.\n"
        "Use /start to resubscribe at any time."
    )
