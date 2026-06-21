from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, BigInteger, JSON, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ImmSource(Base):
    __tablename__ = "imm_sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False, unique=True)
    category = Column(String(50))       # FEDERAL, PROVINCIAL, SPECIAL
    province_code = Column(String(5))   # ON, BC, AB, SK, MB, NS, NB, PE, NL, NT, YT, QC, NU
    last_content_hash = Column(String(64))
    last_checked_at = Column(DateTime)
    last_changed_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    consecutive_errors = Column(Integer, default=0)


class ImmChange(Base):
    __tablename__ = "imm_changes"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("imm_sources.id"))
    detected_at = Column(DateTime, default=datetime.utcnow)
    content_snippet = Column(Text)
    analysis = Column(JSON)
    impact_level = Column(String(20))   # CRITICAL, HIGH, MEDIUM, LOW
    sentiment = Column(String(20))      # POSITIVE, NEGATIVE, NEUTRAL
    affected_case_types = Column(JSON)
    affected_provinces = Column(JSON)
    notifications_sent = Column(Boolean, default=False)


class ImmSubscriber(Base):
    __tablename__ = "imm_subscribers"
    id = Column(Integer, primary_key=True)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=False)
    telegram_username = Column(String(100))
    name = Column(String(200))
    email = Column(String(200))
    province_filters = Column(JSON, default=list)     # [] = all provinces
    case_type_filters = Column(JSON, default=list)    # [] = all case types
    alert_level_minimum = Column(String(20), default="MEDIUM")
    is_active = Column(Boolean, default=True)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    last_alert_at = Column(DateTime)


class ImmNotificationLog(Base):
    __tablename__ = "imm_notification_logs"
    id = Column(Integer, primary_key=True)
    change_id = Column(Integer, ForeignKey("imm_changes.id"))
    subscriber_id = Column(Integer, ForeignKey("imm_subscribers.id"))
    channel = Column(String(20))        # TELEGRAM, EMAIL
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean)
    error_message = Column(String(500))
