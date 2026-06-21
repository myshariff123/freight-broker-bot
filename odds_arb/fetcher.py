import logging
import os
import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4"

# Rotated in order — 4 sports × 1 request each per scan = 4 requests/scan
# At every-4-hour interval: 4 × 6 = 24/day × 31 = 744/month
# Well within 500/month on conservative 6-hour interval (4 × 4 = 16/day × 31 = 496)
SPORTS = [
    ("icehockey_nhl",        "NHL Hockey"),
    ("basketball_nba",       "NBA Basketball"),
    ("soccer_epl",           "EPL Soccer"),
    ("americanfootball_nfl", "NFL Football"),
]


async def get_odds(client: httpx.AsyncClient, sport_key: str) -> list[dict]:
    """Fetch live head-to-head odds for a sport across all available bookmakers."""
    try:
        resp = await client.get(
            f"{BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": os.environ["ODDS_API_KEY"],
                "regions": "ca,us,uk,eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        if resp.status_code == 422:
            logger.debug(f"{sport_key}: not in season")
            return []
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        events = resp.json()
        logger.info(f"{sport_key}: {len(events)} events | API quota remaining: {remaining}")
        return events
    except Exception as e:
        logger.warning(f"Odds API failed [{sport_key}]: {e}")
        return []
