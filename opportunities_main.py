"""
Runs Price Glitch Monitor and Class Action Tracker concurrently in one process.
Both use only public websites — no API keys required.
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from price_glitch.main import run as run_price_glitch
from classaction.main import run as run_classaction


async def main():
    await asyncio.gather(
        run_price_glitch(),
        run_classaction(),
    )


if __name__ == "__main__":
    asyncio.run(main())
