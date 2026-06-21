import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from telegram import Bot

from .analyzer import analyze_change
from .models import ImmSource, ImmChange, ImmSubscriber, ImmNotificationLog
from .notifier import send_telegram_alert, send_email_alert
from .scraper import fetch_and_hash
from .sources import SOURCES

logger = logging.getLogger(__name__)

IMPACT_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def seed_sources(session: Session):
    added = 0
    for src in SOURCES:
        if not session.query(ImmSource).filter_by(url=src.url).first():
            session.add(ImmSource(
                name=src.name,
                url=src.url,
                category=src.category,
                province_code=src.province_code,
                is_active=True,
            ))
            added += 1
    session.commit()
    total = session.query(ImmSource).count()
    logger.info(f"Sources seeded — {added} new, {total} total active")


async def _check_one(source_id: int, session_factory, bot: Bot):
    session: Session = session_factory()
    try:
        source = session.query(ImmSource).filter_by(id=source_id).first()
        if not source:
            return

        content_hash, snippet, error = await fetch_and_hash(source.url)
        source.last_checked_at = datetime.utcnow()

        if error:
            source.consecutive_errors = (source.consecutive_errors or 0) + 1
            if source.consecutive_errors >= 3:
                logger.warning(f"[ERR×{source.consecutive_errors}] {source.name}: {error}")
            session.commit()
            return

        source.consecutive_errors = 0

        # First visit — establish baseline, no alert
        if source.last_content_hash is None:
            source.last_content_hash = content_hash
            session.commit()
            logger.info(f"[BASELINE] {source.name}")
            return

        if content_hash == source.last_content_hash:
            session.commit()
            return

        logger.info(f"[CHANGED] {source.name}")
        source.last_content_hash = content_hash
        source.last_changed_at = datetime.utcnow()
        session.commit()

        # Analyse the change
        try:
            analysis = await analyze_change(
                name=source.name,
                url=source.url,
                category=source.category,
                province=source.province_code,
                content=snippet or "",
            )
        except Exception as e:
            logger.error(f"Analysis error for {source.name}: {e}")
            return

        if not analysis.get("is_meaningful_change", True):
            logger.info(f"[SKIP non-meaningful] {source.name}")
            return

        # Persist change record
        change = ImmChange(
            source_id=source.id,
            content_snippet=(snippet or "")[:2000],
            analysis=analysis,
            impact_level=analysis.get("impact_level", "MEDIUM"),
            sentiment=analysis.get("sentiment", "NEUTRAL"),
            affected_case_types=analysis.get("affected_case_types", []),
            affected_provinces=analysis.get("affected_provinces", ["ALL"]),
        )
        session.add(change)
        session.flush()  # get change.id

        # Notify matching subscribers
        subscribers = session.query(ImmSubscriber).filter_by(is_active=True).all()
        change_impact_val = IMPACT_ORDER.get(change.impact_level, 2)
        change_provinces = set(change.affected_provinces or ["ALL"])
        notified = 0

        for sub in subscribers:
            # Minimum impact filter
            min_val = IMPACT_ORDER.get(sub.alert_level_minimum or "MEDIUM", 2)
            if change_impact_val < min_val:
                continue

            # Province filter (only applied to PROVINCIAL category alerts)
            if sub.province_filters and source.category == "PROVINCIAL":
                if "ALL" not in change_provinces and not change_provinces.intersection(
                    set(sub.province_filters)
                ):
                    continue

            # Telegram
            tg_ok = await send_telegram_alert(bot, sub.telegram_chat_id,
                                               source.name, source.url, analysis)
            session.add(ImmNotificationLog(
                change_id=change.id, subscriber_id=sub.id,
                channel="TELEGRAM", success=tg_ok,
            ))

            # Email (if configured)
            if sub.email:
                email_ok = send_email_alert(sub.email, source.name, source.url, analysis)
                session.add(ImmNotificationLog(
                    change_id=change.id, subscriber_id=sub.id,
                    channel="EMAIL", success=email_ok,
                ))

            sub.last_alert_at = datetime.utcnow()
            notified += 1

        change.notifications_sent = True
        session.commit()
        logger.info(
            f"[ALERT SENT] {source.name} | {change.impact_level} | "
            f"{change.sentiment} | {notified} subscriber(s)"
        )

    except Exception as e:
        logger.error(f"Unexpected error checking {source_id}: {e}", exc_info=True)
    finally:
        session.close()


async def run_monitoring_cycle(session_factory, bot: Bot):
    tmp: Session = session_factory()
    source_ids = [s.id for s in tmp.query(ImmSource).filter_by(is_active=True).all()]
    tmp.close()

    logger.info(f"Monitoring cycle — checking {len(source_ids)} sources")
    # Check in batches of 5 (polite to government servers)
    for i in range(0, len(source_ids), 5):
        batch = source_ids[i:i + 5]
        await asyncio.gather(*[_check_one(sid, session_factory, bot) for sid in batch])
        await asyncio.sleep(3)
    logger.info("Monitoring cycle complete")


def start_scheduler(session_factory, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_monitoring_cycle,
        trigger="interval",
        minutes=15,
        args=[session_factory, bot],
        id="imm_monitor",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("Scheduler started — immigration sources checked every 15 minutes")
    return scheduler
