import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import create_engine, text

load_dotenv()

app = FastAPI(title="Bot Command Center", docs_url=None, redoc_url=None)

_engine = None

STATIC_DIR = Path(__file__).parent / "static"
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPC = "https://polygon-rpc.com"


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _q(sql: str, params: dict | None = None):
    with engine().connect() as conn:
        return conn.execute(text(sql), params or {}).mappings().fetchall()


def _scalar(sql: str, params: dict | None = None):
    with engine().connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/summary")
def summary():
    try:
        row = _q("""
            SELECT
              COALESCE(SUM(pnl_usdc), 0)                                        AS total_pnl,
              COUNT(*)                                                           AS total_trades,
              COUNT(*) FILTER (WHERE status = 'open')                           AS open_positions,
              COUNT(*) FILTER (WHERE pnl_usdc > 0)                              AS wins,
              COUNT(*) FILTER (WHERE pnl_usdc IS NOT NULL AND pnl_usdc <= 0)    AS losses
            FROM listing_sniper_positions
        """)[0]
        closed = max(1, (row["wins"] or 0) + (row["losses"] or 0))
        win_rate = round((row["wins"] or 0) / closed * 100, 1)

        arb_today = _scalar(
            "SELECT COUNT(*) FROM arb_opportunities WHERE found_at >= NOW() - INTERVAL '24 hours'"
        ) or 0
        arb_total = _scalar("SELECT COUNT(*) FROM arb_opportunities") or 0
        best_margin = _scalar("SELECT MAX(margin_pct) FROM arb_opportunities") or 0

        ca_total = _scalar("SELECT COUNT(*) FROM classaction_settlements WHERE alerted = true") or 0
        products_tracked = _scalar("SELECT COUNT(DISTINCT sku) FROM price_glitch_baselines") or 0

        return {
            "total_pnl": round(float(row["total_pnl"] or 0), 2),
            "total_trades": row["total_trades"] or 0,
            "open_positions": row["open_positions"] or 0,
            "wins": row["wins"] or 0,
            "losses": row["losses"] or 0,
            "win_rate": win_rate,
            "arb_today": arb_today,
            "arb_total": arb_total,
            "best_margin": round(float(best_margin or 0), 2),
            "ca_settlements": ca_total,
            "products_tracked": products_tracked,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/positions")
def positions(status: str = "all"):
    where = "" if status == "all" else f"WHERE status = '{status}'"
    try:
        rows = _q(f"""
            SELECT id, token_symbol, exchange, pair, buy_usdc,
                   sell_usdc, pnl_usdc, status, opened_at, closed_at, buy_tx, sell_tx
            FROM listing_sniper_positions
            {where}
            ORDER BY opened_at DESC
            LIMIT 200
        """)
        result = []
        for r in rows:
            age_h = None
            if r["opened_at"]:
                end = r["closed_at"] or datetime.now(timezone.utc)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                opened = r["opened_at"]
                if opened.tzinfo is None:
                    opened = opened.replace(tzinfo=timezone.utc)
                age_h = round((end - opened).total_seconds() / 3600, 1)

            pnl = r["pnl_usdc"]
            buy = r["buy_usdc"] or 0
            pct = round((pnl / buy) * 100, 1) if pnl is not None and buy > 0 else None

            result.append({
                "id": r["id"],
                "token": r["token_symbol"],
                "exchange": r["exchange"],
                "pair": r["pair"],
                "buy_usdc": r["buy_usdc"],
                "sell_usdc": r["sell_usdc"],
                "pnl_usdc": round(pnl, 2) if pnl is not None else None,
                "pnl_pct": pct,
                "status": r["status"],
                "opened_at": r["opened_at"].isoformat() if r["opened_at"] else None,
                "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
                "age_hours": age_h,
                "buy_tx": r["buy_tx"],
                "sell_tx": r["sell_tx"],
            })
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/pnl-chart")
def pnl_chart():
    try:
        rows = _q("""
            SELECT DATE(closed_at AT TIME ZONE 'UTC') AS day,
                   SUM(pnl_usdc)                       AS daily_pnl,
                   COUNT(*)                            AS trades
            FROM listing_sniper_positions
            WHERE status != 'open' AND closed_at IS NOT NULL
            GROUP BY day
            ORDER BY day ASC
            LIMIT 60
        """)
        labels, values, running = [], [], []
        cumulative = 0.0
        for r in rows:
            labels.append(r["day"].strftime("%b %d") if r["day"] else "")
            values.append(round(float(r["daily_pnl"] or 0), 2))
            cumulative += float(r["daily_pnl"] or 0)
            running.append(round(cumulative, 2))
        return {"labels": labels, "daily": values, "cumulative": running}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/arb")
def arb_opportunities(limit: int = 50):
    try:
        rows = _q(f"""
            SELECT id, sport, home_team, away_team, margin_pct,
                   stakes_json, commence_time, found_at
            FROM arb_opportunities
            ORDER BY found_at DESC
            LIMIT {min(limit, 200)}
        """)
        result = []
        for r in rows:
            stakes = {}
            try:
                stakes = json.loads(r["stakes_json"] or "{}")
            except Exception:
                pass
            result.append({
                "id": r["id"],
                "sport": r["sport"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "margin_pct": round(float(r["margin_pct"] or 0), 2),
                "profit_per_100": round(float(r["margin_pct"] or 0), 2),
                "stakes": stakes,
                "commence_time": r["commence_time"].isoformat() if r["commence_time"] else None,
                "found_at": r["found_at"].isoformat() if r["found_at"] else None,
            })
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/alerts/glitch")
def glitch_alerts():
    try:
        rows = _q("""
            SELECT DISTINCT ON (sku) sku, name, source, url,
                   avg_price_30d, min_price_30d, sample_count, last_updated
            FROM price_glitch_baselines
            ORDER BY sku, last_updated DESC
            LIMIT 100
        """)
        # also get latest recorded price
        result = []
        for r in rows:
            latest = _scalar(
                "SELECT price FROM price_glitch_records WHERE sku = :sku ORDER BY recorded_at DESC LIMIT 1",
                {"sku": r["sku"]}
            )
            avg = float(r["avg_price_30d"] or 0)
            cur = float(latest or avg)
            pct_off = round((1 - cur / avg) * 100, 1) if avg > 0 else 0
            result.append({
                "sku": r["sku"],
                "name": r["name"],
                "source": r["source"],
                "url": r["url"],
                "current_price": round(cur, 2),
                "avg_price": round(avg, 2),
                "pct_off": pct_off,
                "samples": r["sample_count"],
                "last_updated": r["last_updated"].isoformat() if r["last_updated"] else None,
                "is_glitch": cur < avg * 0.40 and (avg - cur) >= 50,
            })
        result.sort(key=lambda x: x["pct_off"], reverse=True)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/alerts/classaction")
def classaction():
    try:
        rows = _q("""
            SELECT id, title, url, source, excerpt, date_posted, alerted, first_seen
            FROM classaction_settlements
            ORDER BY first_seen DESC
            LIMIT 100
        """)
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "source": r["source"],
                "excerpt": r["excerpt"],
                "date_posted": r["date_posted"],
                "alerted": r["alerted"],
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/system")
def system():
    now = datetime.now(timezone.utc)

    def last_activity(table: str, col: str = "created_at") -> str | None:
        try:
            ts = _scalar(f"SELECT MAX({col}) FROM {table}")
            if ts:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                mins = int((now - ts).total_seconds() / 60)
                return f"{mins}m ago" if mins < 120 else f"{mins // 60}h ago"
        except Exception:
            pass
        return None

    bots = [
        {
            "name": "Listing Sniper",
            "icon": "🎯",
            "last_seen": last_activity("listing_sniper_pairs", "first_seen"),
            "detail": f"{_scalar('SELECT COUNT(*) FROM listing_sniper_pairs') or 0:,} pairs tracked",
        },
        {
            "name": "Odds Arb",
            "icon": "🎰",
            "last_seen": last_activity("arb_opportunities", "found_at"),
            "detail": f"{_scalar('SELECT COUNT(*) FROM arb_opportunities') or 0} opportunities found",
        },
        {
            "name": "Price Glitch",
            "icon": "💸",
            "last_seen": last_activity("price_glitch_records", "recorded_at"),
            "detail": f"{_scalar('SELECT COUNT(DISTINCT sku) FROM price_glitch_baselines') or 0} products monitored",
        },
        {
            "name": "Class Action",
            "icon": "⚖️",
            "last_seen": last_activity("classaction_settlements", "first_seen"),
            "detail": f"{_scalar('SELECT COUNT(*) FROM classaction_settlements WHERE alerted=true') or 0} Canada alerts sent",
        },
    ]

    wallet = {"matic": None, "usdc": None, "address": None, "error": None}
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
        pk = os.environ.get("PRIVATE_KEY", "")
        if pk:
            acct = w3.eth.account.from_key(pk)
            addr = acct.address
            matic = w3.eth.get_balance(addr)
            usdc_contract = w3.eth.contract(
                address=Web3.to_checksum_address(USDC_POLYGON), abi=ERC20_ABI
            )
            usdc_raw = usdc_contract.functions.balanceOf(addr).call()
            wallet = {
                "address": addr,
                "matic": round(matic / 1e18, 4),
                "usdc": round(usdc_raw / 1e6, 2),
                "error": None,
            }
    except Exception as e:
        wallet["error"] = str(e)

    return {"bots": bots, "wallet": wallet, "timestamp": now.isoformat()}
