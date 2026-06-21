from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
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


class Position(Base):
    __tablename__ = "listing_sniper_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_address = Column(String, index=True)
    token_symbol = Column(String)
    exchange = Column(String)
    pair = Column(String)
    buy_usdc = Column(Float)
    buy_tx = Column(String)
    opened_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sell_tx = Column(String, nullable=True)
    sell_usdc = Column(Float, nullable=True)
    pnl_usdc = Column(Float, nullable=True)
    status = Column(String, default="open")  # open | sold | stopped | failed
    closed_at = Column(DateTime(timezone=True), nullable=True)
