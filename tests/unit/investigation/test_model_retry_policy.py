import httpx
import pytest
from openai import APIStatusError

from marketpulse.investigation.harness.model_retry import retryable_model_error
from marketpulse.investigation.recording.errors import ProviderCallError


@pytest.mark.parametrize(
    "status,expected", [(400, False), (402, False), (429, True), (500, True), (503, True)]
)
def test_retry_http_categories(status, expected):
    error = ProviderCallError("provider failure")
    error.__cause__ = APIStatusError(
        "redacted",
        response=httpx.Response(status, request=httpx.Request("POST", "https://api.test")),
        body=None,
    )
    assert retryable_model_error(error) is expected


def test_wrapped_connection_interruption_is_retryable():
    error = ProviderCallError("provider failure")
    error.__cause__ = httpx.ReadError("redacted")
    assert retryable_model_error(error)


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionResetError()])
def test_wrapped_builtin_transport_error_is_retryable(failure):
    error = ProviderCallError("provider failure")
    error.__cause__ = failure
    assert retryable_model_error(error)
