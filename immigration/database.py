import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

logger = logging.getLogger(__name__)


def init_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set in environment")
    engine = create_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    Base.metadata.create_all(engine)
    logger.info("Immigration DB tables created/verified")
    return sessionmaker(bind=engine)
