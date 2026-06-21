from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Carrier(Base):
    __tablename__ = "carriers"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(200), unique=True, nullable=False)
    city = Column(String(100))
    province = Column(String(10), default="AB")
    phone = Column(String(50))
    email = Column(String(200))
    website = Column(String(300))
    address = Column(String(300))
    typical_equipment = Column(String(100), default="Dry Van")
    home_province = Column(String(10), default="AB")
    preferred_lanes = Column(Text)       # JSON: ["AB-BC", "AB-ON"]
    google_rating = Column(Float, default=0)
    source = Column(String(50))          # yellowpages, google_places, manual
    status = Column(String(30), default="uncontacted")  # uncontacted, contacted, active, inactive
    notes = Column(Text)
    last_used = Column(DateTime)
    loads_completed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class CarrierLane(Base):
    __tablename__ = "carrier_lanes"

    id = Column(Integer, primary_key=True)
    carrier_id = Column(Integer, nullable=False)
    origin_province = Column(String(10))
    destination_province = Column(String(10))
    typical_rate_low = Column(Float)
    typical_rate_high = Column(Float)
    equipment_type = Column(String(50))
    confirmed = Column(Integer, default=0)  # 0=estimated, 1=confirmed by carrier
