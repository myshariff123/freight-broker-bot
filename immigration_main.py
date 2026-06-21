import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

from immigration.commands import (
    cmd_email, cmd_history, cmd_level, cmd_pause,
    cmd_provinces, cmd_resume, cmd_start, cmd_status, cmd_stop, cmd_summary,
)
from immigration.database import init_db
from immigration.scheduler import seed_sources, start_scheduler

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    session_factory = application.bot_data["db_session"]

    session = session_factory()
    seed_sources(session)
    session.close()

    scheduler = start_scheduler(session_factory, application.bot)
    application.bot_data["scheduler"] = scheduler

    logger.info("ImmAlert Canada bot started — monitoring 27 Canadian immigration sources")


async def post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def main():
    token = os.getenv("IMM_TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("IMM_TELEGRAM_BOT_TOKEN not set")

    session_factory = init_db()

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.bot_data["db_session"] = session_factory

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("email", cmd_email))
    app.add_handler(CommandHandler("provinces", cmd_provinces))
    app.add_handler(CommandHandler("level", cmd_level))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("stop", cmd_stop))

    logger.info("Starting ImmAlert Canada polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
