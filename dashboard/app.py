"""
Simple FastAPI dashboard — view daily P&L, load pipeline, history.
Access at http://YOUR_EC2_IP:8080
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from tracker.database import SessionLocal, init_db
from tracker.models import Load, LoadStatus, DailyStats
from datetime import date, timedelta
import os

app = FastAPI(title="Freight Broker Bot Dashboard")
templates = Jinja2Templates(directory="/app/dashboard/templates")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = SessionLocal()
    try:
        today = date.today().isoformat()

        # Today's stats
        today_stats = db.query(DailyStats).filter_by(date=today).first()

        # Last 7 days
        week_stats = (
            db.query(DailyStats)
            .filter(DailyStats.date >= (date.today() - timedelta(days=7)).isoformat())
            .order_by(desc(DailyStats.date))
            .all()
        )

        # Recent opportunities (last 50)
        recent_loads = (
            db.query(Load)
            .filter(Load.status.in_([LoadStatus.ALERTED, LoadStatus.BOOKED, LoadStatus.IN_TRANSIT,
                                     LoadStatus.DELIVERED, LoadStatus.PAID]))
            .order_by(desc(Load.first_seen_at))
            .limit(50)
            .all()
        )

        # Pipeline
        booked = db.query(Load).filter(Load.status == LoadStatus.BOOKED).count()
        in_transit = db.query(Load).filter(Load.status == LoadStatus.IN_TRANSIT).count()
        paid_today = db.query(Load).filter(
            Load.status == LoadStatus.PAID,
            Load.paid_at >= today
        ).count()

        total_profit = sum(s.net_profit for s in week_stats)

        return templates.TemplateResponse("index.html", {
            "request": request,
            "today_stats": today_stats,
            "week_stats": week_stats,
            "recent_loads": recent_loads,
            "booked": booked,
            "in_transit": in_transit,
            "paid_today": paid_today,
            "total_week_profit": total_profit,
            "today": today,
        })
    finally:
        db.close()


@app.post("/mark-paid/{loadlink_id}")
async def mark_paid(loadlink_id: str, actual_shipper_rate: float, actual_carrier_rate: float):
    """Mark a load as paid and record actual profit."""
    db = SessionLocal()
    try:
        load = db.query(Load).filter_by(loadlink_id=loadlink_id).first()
        if not load:
            return {"error": "Load not found"}

        profit = actual_shipper_rate - actual_carrier_rate
        load.status = LoadStatus.PAID
        load.actual_carrier_rate = actual_carrier_rate
        load.actual_profit = profit
        from datetime import datetime
        load.paid_at = datetime.utcnow()

        today = date.today().isoformat()
        stats = db.query(DailyStats).filter_by(date=today).first()
        if stats:
            stats.loads_paid += 1
            stats.gross_revenue += actual_shipper_rate
            stats.carrier_costs += actual_carrier_rate
            stats.net_profit += profit

        db.commit()
        return {"success": True, "profit": profit}
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}
