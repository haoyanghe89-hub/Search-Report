from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import AnalysisProposal
from marketpulse.investigation.domain.enums import ExternalCallStatus
from marketpulse.investigation.ports.external import ModelMessage, ModelRequest
from marketpulse.investigation.recording.adapters import CallContext, RecordingModelAdapter
from marketpulse.investigation.recording.errors import ProviderCallError


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [400, None])
async def test_model_failure_records_safe_diagnostics_without_changing_retry_policy(http_status):
    secret = "PRIVATE-PROMPT-AND-API-KEY"
    request = httpx.Request("POST", "https://example.test/" + secret)
    if http_status:
        failure = BadRequestError(
            secret, response=httpx.Response(http_status, request=request), body={"error": secret}
        )
        expected = {"category": "http_error", "http_status": http_status}
    else:
        failure = APIConnectionError(request=request, message=secret)
        failure.__cause__ = httpx.ConnectError(secret, request=request)
        expected = {"category": "connection_error", "transport_category": "connect_error"}
    create = AsyncMock(side_effect=failure)
    live = OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="fixture",
        default_model="fixture",
    )
    store = Mock()
    from marketpulse.infrastructure.storage.models import BlobRef

    store.put_payload.return_value = BlobRef(sha256="a" * 64)
    recorder = RecordingModelAdapter(live, store, CallContext("run", "step"))
    with pytest.raises(ProviderCallError):
        await recorder.generate(
            ModelRequest(
                messages=(ModelMessage(role="user", content="test"),),
                response_model=AnalysisProposal,
                response_schema_version="v1",
                prompt_version="v1",
            )
        )
    record = store.add_model_call.call_args.args[0]
    assert record.metadata["provider_diagnostics"] == expected
    assert record.status == ExternalCallStatus.PROVIDER_ERROR
    assert not record.replayable
    assert secret not in record.model_dump_json()
    assert create.await_count == 1
