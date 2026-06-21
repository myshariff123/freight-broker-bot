def find_best_odds(event: dict, market_key: str = "h2h") -> dict[str, tuple[float, str]]:
    """For each outcome, find the single bookmaker offering the highest price."""
    best: dict[str, tuple[float, str]] = {}
    for bookmaker in event.get("bookmakers", []):
        title = bookmaker.get("title", bookmaker["key"])
        for market in bookmaker.get("markets", []):
            if market["key"] != market_key:
                continue
            for outcome in market["outcomes"]:
                name = outcome["name"]
                price = float(outcome["price"])
                if name not in best or price > best[name][0]:
                    best[name] = (price, title)
    return best


def arb_margin(best: dict[str, tuple[float, str]]) -> float | None:
    """Return guaranteed profit % if an arbitrage exists across the given odds, else None."""
    if len(best) < 2:
        return None
    total_implied = sum(1.0 / price for price, _ in best.values())
    if total_implied >= 1.0:
        return None
    return round((1.0 - total_implied) * 100, 3)


def optimal_stakes(best: dict[str, tuple[float, str]], bankroll: float) -> dict:
    """Compute stake per outcome so payout is equal regardless of result."""
    total_implied = sum(1.0 / price for price, _ in best.values())
    result = {}
    for outcome, (price, book) in best.items():
        stake = round(bankroll * (1.0 / price) / total_implied, 2)
        result[outcome] = {
            "book": book,
            "odds": price,
            "stake": stake,
            "payout": round(stake * price, 2),
        }
    return result
