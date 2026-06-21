import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

IMPACT_EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📋", "LOW": "ℹ️"}
SENTIMENT_EMOJI = {"POSITIVE": "✅", "NEGATIVE": "❌", "NEUTRAL": "↔️"}
IMPACT_COLOR = {
    "CRITICAL": "#c62828", "HIGH": "#e65100", "MEDIUM": "#1565c0", "LOW": "#2e7d32"
}


def _tg_message(source_name: str, url: str, a: dict) -> str:
    ie = IMPACT_EMOJI.get(a.get("impact_level", "MEDIUM"), "📋")
    se = SENTIMENT_EMOJI.get(a.get("sentiment", "NEUTRAL"), "↔️")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    impact = a.get("impact_level", "MEDIUM")
    cases = a.get("affected_case_types", [])
    cases_str = ", ".join(cases[:5]) + ("…" if len(cases) > 5 else "") if cases else "General"
    actions = a.get("rcic_immediate_actions", [])
    actions_str = "\n".join(f"  • {x}" for x in actions[:4])

    msg = (
        f"{ie} *{impact}* {se} *{a.get('sentiment','NEUTRAL')}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *{source_name}*\n"
        f"🕐 {ts}\n\n"
        f"*WHAT CHANGED*\n"
        f"{a.get('summary','')}\n\n"
        f"*DETAIL*\n"
        f"{a.get('what_changed_detail','')[:400]}\n\n"
        f"*AFFECTED CASES*\n{cases_str}\n\n"
        f"*CLIENT IMPACT*\n{a.get('client_impact','')}\n"
    )
    if a.get("deadline_sensitive"):
        msg += f"\n⏰ *DEADLINE:* {a.get('deadline_details','')}\n"
    if actions_str:
        msg += f"\n*RCIC ACTIONS*\n{actions_str}\n"
    if a.get("positive_aspects"):
        msg += f"\n✅ *Positive:* {a['positive_aspects']}\n"
    if a.get("negative_aspects"):
        msg += f"\n❌ *Concern:* {a['negative_aspects']}\n"
    msg += f"\n🔗 [View Source]({url})"
    return msg


def _email_content(source_name: str, url: str, a: dict) -> tuple[str, str]:
    impact = a.get("impact_level", "MEDIUM")
    sentiment = a.get("sentiment", "NEUTRAL")
    ie = IMPACT_EMOJI.get(impact, "📋")
    se = SENTIMENT_EMOJI.get(sentiment, "↔️")
    color = IMPACT_COLOR.get(impact, "#1565c0")
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    subject = f"{ie} [{impact}] {source_name} — Canadian Immigration Policy Change"

    cases = a.get("affected_case_types", [])
    badges = "".join(
        f'<span style="background:#e3f2fd;padding:3px 10px;border-radius:12px;'
        f'margin:3px;display:inline-block;font-size:13px">{c}</span>'
        for c in cases
    ) or "<em>General</em>"

    actions_html = "".join(
        f"<li style='margin:4px 0'>{x}</li>"
        for x in a.get("rcic_immediate_actions", [])
    )
    deadline_block = (
        f'<div style="background:#fff3e0;border-left:4px solid #e65100;'
        f'padding:12px 16px;margin:16px 0;border-radius:4px">'
        f'<strong>⏰ DEADLINE:</strong> {a.get("deadline_details","")}</div>'
        if a.get("deadline_sensitive") else ""
    )
    positive = (
        f'<p><strong style="color:#2e7d32">✅ Positive:</strong> {a["positive_aspects"]}</p>'
        if a.get("positive_aspects") else ""
    )
    negative = (
        f'<p><strong style="color:#c62828">❌ Concern:</strong> {a["negative_aspects"]}</p>'
        if a.get("negative_aspects") else ""
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>body{{font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333}}
h3{{color:{color};margin-top:20px}}</style></head>
<body>
<div style="background:{color};color:white;padding:18px 22px;border-radius:8px 8px 0 0">
  <h2 style="margin:0">{ie} {impact} IMMIGRATION ALERT &nbsp; {se} {sentiment}</h2>
  <p style="margin:4px 0 0;opacity:.85;font-size:14px">{ts} &nbsp;|&nbsp; {source_name}</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:22px;border-radius:0 0 8px 8px">
  <p><strong>Source:</strong> <a href="{url}">{url}</a></p>
  <hr style="border:none;border-top:1px solid #eee">
  <h3>What Changed</h3>
  <p>{a.get("summary","")}</p>
  <h3>Detailed Change</h3>
  <p>{a.get("what_changed_detail","")}</p>
  <h3>Affected Case Types</h3>
  <p>{badges}</p>
  <h3>Client Impact</h3>
  <p>{a.get("client_impact","")}</p>
  <h3>Affected Applicant Profiles</h3>
  <p>{a.get("affected_applicant_profiles","")}</p>
  {deadline_block}
  <h3>Immediate RCIC Actions</h3>
  <ul style="padding-left:20px">{actions_html}</ul>
  {positive}
  {negative}
  <hr style="border:none;border-top:1px solid #eee;margin-top:24px">
  <p style="font-size:12px;color:#888">
    ImmAlert Canada — Real-time immigration policy monitoring for RCICs and immigration lawyers.<br>
    Manage your alerts by messaging your ImmAlert Telegram bot.
  </p>
</div>
</body></html>"""
    return subject, html


async def send_telegram_alert(bot: Bot, chat_id: int,
                               source_name: str, url: str, analysis: dict) -> bool:
    try:
        msg = _tg_message(source_name, url, analysis)
        await bot.send_message(
            chat_id=chat_id, text=msg,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"Telegram send failed → {chat_id}: {e}")
        return False


def send_email_alert(to_email: str, source_name: str, url: str, analysis: dict) -> bool:
    gmail_user = os.getenv("GMAIL_ADDRESS")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pass:
        logger.warning("Gmail credentials not configured — skipping email")
        return False
    try:
        subject, html = _email_content(source_name, url, analysis)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"ImmAlert Canada <{gmail_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(gmail_user, gmail_pass)
            srv.sendmail(gmail_user, to_email, msg.as_string())
        logger.info(f"Email sent → {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email send failed → {to_email}: {e}")
        return False
