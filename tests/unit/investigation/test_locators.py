from __future__ import annotations

import hashlib

import pytest

from marketpulse.investigation.domain.locators import (
    PdfTextRangeLocator,
    TextRangeLocator,
    deserialize_locator,
    serialize_locator,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.parametrize(
    "locator",
    [
        TextRangeLocator(start=5, end=12, quote_hash=_hash("example")),
        PdfTextRangeLocator(page=3, start=7, end=18, quote_hash=_hash("page quote")),
    ],
)
def test_locator_round_trip_is_canonical(locator: object) -> None:
    serialized = serialize_locator(locator)  # type: ignore[arg-type]
    assert serialize_locator(deserialize_locator(serialized)) == serialized
    assert " " not in serialized
    assert deserialize_locator(serialized) == locator


def test_text_range_rejects_empty_or_reverse_range() -> None:
    with pytest.raises(ValueError):
        TextRangeLocator(start=10, end=10, quote_hash=_hash("x"))


def test_pdf_locator_requires_one_based_page() -> None:
    with pytest.raises(ValueError):
        PdfTextRangeLocator(page=0, start=0, end=1, quote_hash=_hash("x"))


def test_locator_deserialization_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="locator"):
        deserialize_locator('{"locator_type":"CSS_SELECTOR","selector":"body"}')
