from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from marketpulse.infrastructure.storage.models import BlobRef

EntityId = Annotated[str, Field(min_length=1, max_length=128)]
NonEmptyText = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
BlobReference = Annotated[
    BlobRef,
    PlainSerializer(lambda ref: ref.uri, return_type=str, when_used="json"),
]


class DomainModel(BaseModel):
    """Immutable domain value with strict inputs and portable JSON output."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )
