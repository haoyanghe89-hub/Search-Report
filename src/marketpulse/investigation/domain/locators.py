from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from marketpulse.investigation.domain.base import DomainModel, Sha256


class TextRangeLocator(DomainModel):
    locator_type: Literal["TEXT_RANGE"] = "TEXT_RANGE"
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_hash: Sha256

    def model_post_init(self, __context: object) -> None:
        if self.end <= self.start:
            raise ValueError("locator end must be greater than start")


class PdfTextRangeLocator(DomainModel):
    locator_type: Literal["PDF_TEXT_RANGE"] = "PDF_TEXT_RANGE"
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_hash: Sha256

    def model_post_init(self, __context: object) -> None:
        if self.end <= self.start:
            raise ValueError("locator end must be greater than start")


EvidenceLocator = Annotated[
    TextRangeLocator | PdfTextRangeLocator,
    Field(discriminator="locator_type"),
]
_LOCATOR_ADAPTER: TypeAdapter[EvidenceLocator] = TypeAdapter(EvidenceLocator)


def serialize_locator(locator: EvidenceLocator) -> str:
    return json.dumps(locator.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def deserialize_locator(payload: str) -> EvidenceLocator:
    try:
        raw = json.loads(payload)
        return _LOCATOR_ADAPTER.validate_python(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        raise ValueError("invalid evidence locator payload") from error
