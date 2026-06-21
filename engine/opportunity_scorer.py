from engine.lane_rates import get_market_carrier_rate, get_midpoint_rate
import os

MIN_PROFIT = float(os.getenv("MIN_PROFIT_THRESHOLD", "250"))


def score_load(load_data: dict) -> dict:
    """
    Score a load from Loadlink.
    Returns enriched dict with profit estimates and go/no-go recommendation.
    """
    origin_city = load_data.get("origin_city", "")
    origin_prov = load_data.get("origin_province", "AB")
    dest_city = load_data.get("destination_city", "")
    dest_prov = load_data.get("destination_province", "")
    equipment = load_data.get("equipment_type", "Dry Van")
    posted_rate = load_data.get("shipper_rate", 0.0)  # 0 = negotiable

    carrier_low, carrier_high = get_market_carrier_rate(
        origin_city, origin_prov, dest_city, dest_prov, equipment
    )
    carrier_mid = (carrier_low + carrier_high) / 2

    result = {
        **load_data,
        "market_carrier_rate_low": carrier_low,
        "market_carrier_rate_high": carrier_high,
        "market_carrier_rate": carrier_mid,
        "recommend": False,
        "estimated_profit": 0.0,
        "margin_pct": 0.0,
        "alert_reason": "",
    }

    if posted_rate > 0:
        profit = posted_rate - carrier_mid
        margin_pct = (profit / posted_rate) * 100 if posted_rate else 0
        result["estimated_profit"] = round(profit)
        result["margin_pct"] = round(margin_pct, 1)

        if profit >= MIN_PROFIT:
            result["recommend"] = True
            result["alert_reason"] = f"${profit:.0f} margin ({margin_pct:.1f}%) on posted rate"
        elif profit > 0:
            result["alert_reason"] = f"Margin too thin (${profit:.0f}) — skip"
        else:
            result["alert_reason"] = f"Shipper rate below our carrier cost — skip"

    else:
        # Negotiable rate — we target carrier_high + our margin as ask price
        target_shipper_rate = carrier_high + MIN_PROFIT + 150  # buffer
        result["estimated_profit"] = MIN_PROFIT + 150
        result["margin_pct"] = round(((MIN_PROFIT + 150) / target_shipper_rate) * 100, 1)
        result["target_ask_rate"] = round(target_shipper_rate)
        result["recommend"] = True
        result["alert_reason"] = f"Negotiable — quote ${target_shipper_rate:.0f}, expect ${MIN_PROFIT + 150:.0f} profit"

    return result


def format_profit_tier(profit: float) -> str:
    if profit >= 800:
        return "🔥 FIRE"
    elif profit >= 500:
        return "✅ STRONG"
    elif profit >= 250:
        return "👍 GOOD"
    else:
        return "⚠️ THIN"
