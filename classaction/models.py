from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Settlement(Base):
    __tablename__ = "classaction_settlements"

    id = Column(String, primary_key=True)
    title = Column(String)
    url = Column(String)
    source = Column(String)
    excerpt = Column(Text)
    date_posted = Column(String)
    alerted = Column(Boolean, default=False)
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
