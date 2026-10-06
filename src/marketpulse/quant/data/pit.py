from datetime import date

from ..domain import PITLevel


def classify(dataset: str, provider: str, rows: list[dict]) -> PITLevel:
    if dataset == "financial":
        # pubDate without archived first-seen revisions is not strict historical PIT.
        return (
            PITLevel.PARTIAL
            if rows and all(row.get("published_at") for row in rows)
            else PITLevel.UNAVAILABLE
        )
    if dataset == "valuation":
        return PITLevel.UNAVAILABLE
    # Current feeds can retrospectively revise history, even their unadjusted prices.
    return PITLevel.PARTIAL


def visible_financial(row: dict, asof: date) -> bool:
    published = row.get("published_at")
    # Date-only releases are visible starting the following calendar date, never intraday.
    return bool(published and date.fromisoformat(published) < asof)
