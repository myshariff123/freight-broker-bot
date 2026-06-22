import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ArbitrageOpportunity(Base):
    __tablename__ = "arb_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sport = Column(String)
    home_team = Column(String)
    away_team = Column(String)
    commence_time = Column(DateTime(timezone=True), nullable=True)
    margin_pct = Column(Float)
    stakes_json = Column(Text)
    found_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def stakes(self) -> dict:
        try:
            return json.loads(self.stakes_json or "{}")
        except Exception:
            return {}
