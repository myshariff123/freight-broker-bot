"""
Telegram command handler for freight quotes.

Commands:
  /ltl Calgary AB → Vancouver BC | 4 pallets | 2000 lbs | Jun 20
  /ftl Calgary AB → Toronto ON | 48000 lbs | Jun 22
  /quote (same as /ltl, defaults to LTL)

Bot responds with ranked carrier quotes + your margin calculation.
User clicks Book It → bot completes booking on Freightera.
"""

import logging
import os
import re
from datetime import datetime, date, timedelta
from freightera.quote_bot import FreighteraQuoteBot, ShipmentRequest, CarrierQuote

logger = logging.getLogger(__name__)

MARGIN_PCT = float(os.getenv("BROKER_MARGIN_PCT", "20"))
MIN_PROFIT = float(os.getenv("MIN_PROFIT_THRESHOLD", "50"))


def parse_quote_command(text: str) -> ShipmentRequest | None:
    """
    Parse Telegram command into ShipmentRequest.

    Formats accepted:
      /ltl Calgary AB → Vancouver BC | 4 pallets | 2000 lbs | Jun 20
      /ftl T2P0C9 → V6C1T2 | 20000 lbs | 2026-06-22
      /ltl Calgary → Vancouver | 3 pallets | 1500 lbs
    """
    # Remove command prefix
    text = re.sub(r'^/(ltl|ftl|flatbed|parcel|container|quote)\s*', '', text, flags=re.I).strip()

    freight_type = "ltl"
    original_lower = text.lower()
    if any(x in original_lower for x in ["/ftl", "ftl", "full truckload"]):
        freight_type = "ftl"
    elif any(x in original_lower for x in ["/flatbed", "flatbed", "open deck"]):
        freight_type = "flatbed"

    # Split by | separator
    parts = [p.strip() for p in re.split(r'\|', text)]

    if len(parts) < 1:
        return None

    # Parse route (first part): "Calgary AB → Vancouver BC"
    route = parts[0]
    route_match = re.split(r'→|->|to\b', route, maxsplit=1, flags=re.I)
    if len(route_match) < 2:
        return None

    pickup = route_match[0].strip()
    delivery = route_match[1].strip()

    # Parse items, weight, date from remaining parts
    num_items = 1
    weight_per_item = 500
    pickup_date = (date.today() + timedelta(days=2)).strftime("%m/%d/%Y")
    unit_type = "Pallets"
    description = "General Freight"

    for part in parts[1:]:
        part_lower = part.lower()

        # Date: "Jun 20", "June 20", "2026-06-20", "06/20/2026"
        date_obj = _parse_date(part)
        if date_obj:
            pickup_date = date_obj.strftime("%m/%d/%Y")
            continue

        # Pallets / items: "4 pallets", "3 skids", "10 boxes"
        item_match = re.search(r'(\d+)\s*(pallet|skid|box|crate|piece|item)s?', part_lower)
        if item_match:
            num_items = int(item_match.group(1))
            unit_raw = item_match.group(2)
            unit_map = {"pallet": "Pallets", "skid": "Skids", "box": "Boxes",
                        "crate": "Crates", "piece": "Pieces", "item": "Pieces"}
            unit_type = unit_map.get(unit_raw, "Pallets")
            continue

        # Weight: "2000 lbs", "20000 lb", "10 tons"
        weight_match = re.search(r'([\d,]+)\s*(?:lbs?|pounds?|kg)', part_lower)
        if weight_match:
            total_weight = int(weight_match.group(1).replace(",", ""))
            weight_per_item = max(1, total_weight // max(1, num_items))
            continue

        # Description
        if len(part) > 3 and not any(c.isdigit() for c in part):
            description = part.strip()

    return ShipmentRequest(
        pickup_city=pickup,
        delivery_city=delivery,
        pickup_date=pickup_date,
        freight_type=freight_type,
        num_items=num_items,
        unit_type=unit_type,
        weight_per_item_lbs=weight_per_item,
        description=description,
    )


def _parse_date(text: str) -> date | None:
    text = text.strip()
    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y",
        "%b %d", "%B %d", "%b %d %Y", "%B %d %Y",
        "%b %d, %Y", "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            d = datetime.strptime(text, fmt)
            if d.year == 1900:  # No year given, use current/next year
                d = d.replace(year=date.today().year)
                if d.date() < date.today():
                    d = d.replace(year=date.today().year + 1)
            return d.date()
        except ValueError:
            continue
    return None


def calculate_shipper_price(carrier_price: float, margin_pct: float = MARGIN_PCT) -> dict:
    """Calculate what to charge the shipper for a given carrier cost."""
    markup = carrier_price * (margin_pct / 100)
    shipper_price = carrier_price + markup
    return {
        "carrier_cost": round(carrier_price, 2),
        "markup_cad": round(markup, 2),
        "shipper_price": round(shipper_price, 2),
        "profit": round(markup, 2),
        "margin_pct": margin_pct,
    }


def format_quote_alert(req: ShipmentRequest, quotes: list[CarrierQuote]) -> str:
    """Format carrier quotes into a Telegram message."""
    if not quotes:
        return (
            f"❌ No quotes returned for:\n"
            f"{req.pickup_city} → {req.delivery_city}\n"
            f"({req.num_items} {req.unit_type}, {req.weight_per_item_lbs * req.num_items:,} lbs)\n\n"
            f"Try: different pickup date, adjust dimensions, or check DEBUG screenshots."
        )

    freight_label = req.freight_type.upper()
    total_weight = req.weight_per_item_lbs * req.num_items
    best = quotes[0]
    pricing = calculate_shipper_price(best.price_cad)

    tier = "🔥 GREAT" if pricing["profit"] >= 200 else "✅ GOOD" if pricing["profit"] >= 100 else "👍 OK"

    lines = [
        f"📦 *{freight_label} QUOTES — {req.pickup_city} → {req.delivery_city}*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"📋 {req.num_items} {req.unit_type} | {total_weight:,} lbs | Pickup: {req.pickup_date}",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"*Carrier Quotes ({len(quotes)} received):*",
    ]

    for q in quotes[:8]:  # Show top 8
        marker = "🥇" if q.rank == 1 else "🥈" if q.rank == 2 else "🥉" if q.rank == 3 else f"{q.rank}."
        lines.append(
            f"{marker} *{q.carrier_name}* — ${q.price_cad:,.2f} CAD | {q.transit_days} | {q.service_type}"
        )

    lines += [
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"*Best Option: {best.carrier_name}*",
        f"💰 Carrier cost: ${best.price_cad:,.2f} CAD",
        f"📈 Your price to shipper (+{MARGIN_PCT:.0f}%): *${pricing['shipper_price']:,.2f} CAD*",
        f"✅ *Your profit: ${pricing['profit']:,.2f} CAD* {tier}",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    return "\n".join(lines)


def format_booking_instructions(req: ShipmentRequest, quote: CarrierQuote) -> str:
    pricing = calculate_shipper_price(quote.price_cad)
    return (
        f"📋 *BOOKING INSTRUCTIONS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Route:* {req.pickup_city} → {req.delivery_city}\n"
        f"*Carrier:* {quote.carrier_name}\n"
        f"*Carrier Rate:* ${quote.price_cad:,.2f} CAD\n"
        f"*Your Invoice to Shipper:* ${pricing['shipper_price']:,.2f} CAD\n"
        f"*Your Profit:* ${pricing['profit']:,.2f} CAD\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Steps:*\n"
        f"1. Confirm pickup date with shipper\n"
        f"2. Go to freightera.com → My Quotes → select this quote\n"
        f"3. Complete Step 3 (Shipment Details) — enter shipper/receiver addresses\n"
        f"4. Complete Step 4 (Book Shipment)\n"
        f"5. Invoice your shipper for ${pricing['shipper_price']:,.2f} CAD\n"
        f"6. Reply /paid {req.pickup_city[:3].upper()}{req.delivery_city[:3].upper()} "
        f"${pricing['shipper_price']:.0f} ${quote.price_cad:.0f} to record profit"
    )
