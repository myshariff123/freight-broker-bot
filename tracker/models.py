from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class LoadStatus(str, enum.Enum):
    NEW = "new"
    ALERTED = "alerted"
    SKIPPED = "skipped"
    BOOKED = "booked"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    INVOICED = "invoiced"
    PAID = "paid"


class Load(Base):
    __tablename__ = "loads"

    id = Column(Integer, primary_key=True)
    loadlink_id = Column(String(64), unique=True, nullable=False)
    origin_city = Column(String(100))
    origin_province = Column(String(10))
    destination_city = Column(String(100))
    destination_province = Column(String(10))
    equipment_type = Column(String(50))
    weight_lbs = Column(Integer)
    distance_km = Column(Integer)
    shipper_rate = Column(Float)          # What shipper posted (0 = negotiate)
    market_carrier_rate = Column(Float)   # What we estimate a carrier costs
    estimated_profit = Column(Float)
    margin_pct = Column(Float)
    pickup_date = Column(String(30))
    shipper_name = Column(String(200))
    shipper_phone = Column(String(50))
    shipper_email = Column(String(200))
    notes = Column(Text)
    status = Column(Enum(LoadStatus), default=LoadStatus.NEW)
    raw_data = Column(Text)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    alerted_at = Column(DateTime)
    booked_at = Column(DateTime)
    paid_at = Column(DateTime)
    actual_carrier_rate = Column(Float)
    actual_profit = Column(Float)
    telegram_message_id = Column(Integer)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True)
    date = Column(String(10), unique=True)
    loads_scanned = Column(Integer, default=0)
    opportunities_found = Column(Integer, default=0)
    loads_booked = Column(Integer, default=0)
    loads_paid = Column(Integer, default=0)
    gross_revenue = Column(Float, default=0.0)
    carrier_costs = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
