from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class PriceRecord(Base):
    __tablename__ = "price_glitch_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    name = Column(String)
    source = Column(String)
    url = Column(String)
    price = Column(Float)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PriceBaseline(Base):
    __tablename__ = "price_glitch_baselines"

    sku = Column(String, primary_key=True)
    name = Column(String)
    source = Column(String)
    url = Column(String)
    avg_price_30d = Column(Float)
    min_price_30d = Column(Float)
    max_price_30d = Column(Float)
    sample_count = Column(Integer, default=0)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
