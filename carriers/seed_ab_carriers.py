"""
Hand-seeded list of well-known Alberta carriers to start the database.
These are real, publicly listed companies. Supplement with carrier_builder.py.
Run: docker exec freight-broker-bot python -m carriers.seed_ab_carriers
"""

from tracker.database import init_db, SessionLocal
from carriers.models import Carrier
import logging

logger = logging.getLogger(__name__)

# Publicly known Alberta-based carriers (from public directories, websites, AMTA listings)
SEED_CARRIERS = [
    {
        "company_name": "Mullen Trucking",
        "city": "Aldersyde", "province": "AB",
        "phone": "403-652-1410", "website": "mullen.com",
        "typical_equipment": "Flatbed", "home_province": "AB",
        "preferred_lanes": '["AB-BC","AB-SK","AB-ON"]',
    },
    {
        "company_name": "Bison Transport",
        "city": "Calgary", "province": "AB",
        "phone": "204-783-8833", "website": "bisontransport.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-BC","AB-MB"]',
    },
    {
        "company_name": "Gardewine",
        "city": "Edmonton", "province": "AB",
        "phone": "204-694-6400", "website": "gardewine.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-MB","AB-ON","AB-SK"]',
    },
    {
        "company_name": "Challenger Motor Freight",
        "city": "Calgary", "province": "AB",
        "phone": "519-653-4411", "website": "challenger.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-QC"]',
    },
    {
        "company_name": "Day & Ross",
        "city": "Edmonton", "province": "AB",
        "phone": "506-357-5000", "website": "dayandross.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-QC","AB-BC"]',
    },
    {
        "company_name": "Wheels International",
        "city": "Calgary", "province": "AB",
        "phone": "403-569-3399", "website": "wheelsinternational.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-BC","AB-SK"]',
    },
    {
        "company_name": "Erb Transport",
        "city": "Edmonton", "province": "AB",
        "phone": "519-699-4441", "website": "erbtransport.com",
        "typical_equipment": "Reefer", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-QC","AB-BC"]',
    },
    {
        "company_name": "TFI International (Edmonton)",
        "city": "Edmonton", "province": "AB",
        "phone": "450-419-2388", "website": "tfiintl.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-QC","AB-BC","AB-SK"]',
    },
    {
        "company_name": "Kingsway Transport",
        "city": "Calgary", "province": "AB",
        "phone": "905-677-5600", "website": "kingswayfreight.com",
        "typical_equipment": "Dry Van", "home_province": "AB",
        "preferred_lanes": '["AB-ON","AB-QC"]',
    },
    {
        "company_name": "AV Logistics",
        "city": "Edmonton", "province": "AB",
        "phone": "780-447-4900", "website": "avlogistics.ca",
        "typical_equipment": "Flatbed", "home_province": "AB",
        "preferred_lanes": '["AB-BC","AB-SK"]',
    },
]


def seed():
    init_db()
    db = SessionLocal()
    try:
        added = 0
        for data in SEED_CARRIERS:
            existing = db.query(Carrier).filter_by(company_name=data["company_name"]).first()
            if not existing:
                db.add(Carrier(**data, source="seed", status="uncontacted"))
                added += 1
        db.commit()
        logger.info(f"Seeded {added} carriers")
        print(f"✅ Seeded {added} carriers into database")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
