from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Protocol, TypeVar, cast

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, field_validator

T = TypeVar("T", bound=BaseModel)


class PortModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


class VersionedRequest(PortModel):
    schema_version: str = Field(default="1", min_length=1)
    config_version: str = Field(default="runtime-v1", min_length=1)


class SearchRequest(VersionedRequest):
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=50)
    region: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=32)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class SearchResultItem(PortModel):
    title: str = Field(min_length=1)
    url: AnyHttpUrl
    snippet: str = ""
    rank: int = Field(ge=1)
    source_type_hint: str | None = None
    publisher: str | None = None
    organization: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    is_official: bool | None = None
    is_first_hand: bool | None = None
    quality_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class SearchResult(PortModel):
    items: tuple[SearchResultItem, ...]
    provider: str = Field(min_length=1)
    retrieved_at: datetime


class FetchRequest(VersionedRequest):
    url: AnyHttpUrl
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_bytes: int = Field(default=8 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    accepted_content_types: tuple[str, ...] = (
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/pdf",
    )


class FetchResult(PortModel):
    final_url: AnyHttpUrl
    status_code: int = Field(ge=100, le=599)
    content_type: str = Field(min_length=1)
    body: bytes
    fetched_at: datetime
    headers: dict[str, str] = Field(default_factory=dict)


class ModelMessage(PortModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ModelRequest(VersionedRequest, Generic[T]):
    messages: tuple[ModelMessage, ...]
    response_model: type[T] = Field(exclude=True)
    response_schema_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model_hint: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelUsage(PortModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class StructuredModelResult(PortModel, Generic[T]):
    output: T
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    response_id: str | None = None


class SearchPort(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult: ...


class FetchPort(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...


class ModelPort(Protocol):
    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]: ...


def response_schema(request: ModelRequest[Any]) -> dict[str, Any]:
    return cast(dict[str, Any], request.response_model.model_json_schema())
