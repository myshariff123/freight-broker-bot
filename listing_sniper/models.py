from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class KnownPair(Base):
    __tablename__ = "listing_sniper_pairs"

    exchange = Column(String, primary_key=True)
    pair = Column(String, primary_key=True)
    base_token = Column(String)
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    polygon_addr = Column(String, nullable=True)
    tx_hash = Column(String, nullable=True)
    acted = Column(Boolean, default=False)
