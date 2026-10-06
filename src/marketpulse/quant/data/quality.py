from decimal import Decimal


def quality_flags(rows: list[dict], dataset: str) -> tuple[str, ...]:
    flags: set[str] = set()
    if not rows:
        flags.add("empty_dataset")
    keys = [
        (row.get("instrument_id"), row.get("date") or row.get("period_end"), row.get("metric"))
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        flags.add("duplicate_observations")
    for row in rows:
        if dataset == "daily":
            values = [row.get(field) for field in ("open", "high", "low", "close")]
            if any(value is None for value in values):
                flags.add("missing_ohlc")
            elif row["low"] > min(row["open"], row["close"]) or row["high"] < max(
                row["open"], row["close"]
            ):
                flags.add("invalid_ohlc")
            if row.get("volume") is not None and row["volume"] < 0:
                flags.add("negative_volume")
        if row.get("provisional"):
            flags.add("provisional_bars")
    return tuple(sorted(flags))


def crosscheck(left: list[dict], right: list[dict]) -> dict:
    def index(rows):
        return {(r["instrument_id"], r.get("date")): r for r in rows}

    a, b = index(left), index(right)
    overlap = sorted(a.keys() & b.keys())
    conflicts = []
    for key in overlap:
        for field in ("open", "high", "low", "close", "volume"):
            x, y = a[key].get(field), b[key].get(field)
            if (
                x is not None
                and y is not None
                and abs(Decimal(str(x)) - Decimal(str(y)))
                > (Decimal("0.011") if field != "volume" else Decimal("100"))
            ):
                conflicts.append(
                    {
                        "instrument_id": key[0],
                        "date": key[1],
                        "field": field,
                        "primary": x,
                        "secondary": y,
                    }
                )
    return {
        "overlap": len(overlap),
        "conflicts": conflicts,
        "status": "CONFLICT" if conflicts else "MATCH" if overlap else "UNAVAILABLE",
        "independence": "UNVERIFIED",
        "claims_paused": bool(conflicts) or not overlap,
    }
