"""
Runs Price Glitch Monitor, Class Action Tracker, and Sports Odds Arb concurrently.
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from price_glitch.main import run as run_price_glitch
from classaction.main import run as run_classaction
from odds_arb.main import run as run_odds_arb


async def main():
    await asyncio.gather(
        run_price_glitch(),
        run_classaction(),
        run_odds_arb(),
    )


if __name__ == "__main__":
    asyncio.run(main())
