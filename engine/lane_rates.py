"""
Alberta freight lane rate database.
Rates = typical carrier cost per load (dry van, 53ft, full truckload).
Source: industry averages, updated manually as real data comes in.
Range = (low_cad, high_cad) — we use midpoint as market estimate.
"""

ALBERTA_CARRIER_RATES = {
    # Alberta internal
    ("AB", "AB"): (800, 1300),

    # Alberta → BC
    ("AB", "BC"): (1800, 2600),

    # Alberta → Saskatchewan
    ("AB", "SK"): (900, 1400),

    # Alberta → Manitoba
    ("AB", "MB"): (1600, 2200),

    # Alberta → Ontario
    ("AB", "ON"): (4200, 5800),

    # Alberta → Quebec
    ("AB", "QC"): (5200, 7000),

    # Alberta → Atlantic (NB, NS, NL, PE)
    ("AB", "NB"): (6000, 8000),
    ("AB", "NS"): (6200, 8200),
    ("AB", "NL"): (7000, 9500),
    ("AB", "PE"): (6500, 8500),

    # Inbound to Alberta (when we broker loads INTO AB)
    ("BC", "AB"): (1800, 2600),
    ("SK", "AB"): (900, 1400),
    ("MB", "AB"): (1700, 2300),
    ("ON", "AB"): (4500, 6000),
    ("QC", "AB"): (5500, 7200),
}

# City-pair overrides for high-volume lanes (more precise)
CITY_PAIR_OVERRIDES = {
    ("Calgary", "Vancouver"): (1900, 2500),
    ("Edmonton", "Vancouver"): (2000, 2700),
    ("Calgary", "Edmonton"): (850, 1200),
    ("Edmonton", "Calgary"): (850, 1200),
    ("Calgary", "Kelowna"): (1400, 1900),
    ("Calgary", "Toronto"): (4500, 5800),
    ("Edmonton", "Toronto"): (4200, 5600),
    ("Calgary", "Winnipeg"): (1700, 2300),
    ("Edmonton", "Saskatoon"): (950, 1350),
    ("Calgary", "Regina"): (1100, 1600),
    ("Calgary", "Montreal"): (5500, 7200),
    ("Edmonton", "Fort McMurray"): (1000, 1400),
    ("Calgary", "Lethbridge"): (550, 800),
    ("Edmonton", "Grande Prairie"): (900, 1200),
    ("Calgary", "Red Deer"): (450, 700),
}

EQUIPMENT_MULTIPLIERS = {
    "Dry Van": 1.0,
    "Reefer": 1.25,
    "Flatbed": 1.15,
    "Step Deck": 1.20,
    "RGN": 1.40,
    "Tanker": 1.30,
    "Conestoga": 1.18,
    "B-Train": 1.35,
}


def get_market_carrier_rate(origin_city: str, origin_province: str,
                             destination_city: str, destination_province: str,
                             equipment_type: str = "Dry Van") -> tuple[float, float]:
    """Returns (low_estimate, high_estimate) for carrier cost on this lane."""

    city_key = (origin_city.strip().title(), destination_city.strip().title())
    if city_key in CITY_PAIR_OVERRIDES:
        low, high = CITY_PAIR_OVERRIDES[city_key]
    else:
        prov_key = (origin_province.upper(), destination_province.upper())
        low, high = ALBERTA_CARRIER_RATES.get(prov_key, (1500, 2500))

    multiplier = EQUIPMENT_MULTIPLIERS.get(equipment_type, 1.0)
    return round(low * multiplier), round(high * multiplier)


def get_midpoint_rate(origin_city: str, origin_province: str,
                      destination_city: str, destination_province: str,
                      equipment_type: str = "Dry Van") -> float:
    low, high = get_market_carrier_rate(
        origin_city, origin_province, destination_city, destination_province, equipment_type
    )
    return (low + high) / 2
