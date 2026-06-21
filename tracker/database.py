import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tracker.models import Base as LoadBase
from carriers.models import Base as CarrierBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://freight:password@postgres:5432/freight_bot")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    LoadBase.metadata.create_all(bind=engine)
    CarrierBase.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
