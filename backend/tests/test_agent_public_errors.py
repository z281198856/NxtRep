import httpx
import pytest
from langgraph.errors import GraphRecursionError
from sqlalchemy.exc import OperationalError

from nxtrep_backend.services.agent_errors import public_agent_error
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionResponseError


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError("secret-token"), "AGENT_TIMEOUT"),
        (GraphRecursionError("secret-step-trace"), "AGENT_STEP_LIMIT"),
        (httpx.ConnectError("secret-token"), "AGENT_NETWORK_ERROR"),
        (OperationalError("secret-sql", {}, Exception("secret-token")), "DATA_ACCESS_FAILED"),
    ],
)
def test_public_errors_keep_category_and_hide_sensitive_details(error, code):
    wrapped = RuntimeError("outer secret")
    wrapped.__cause__ = error
    result = public_agent_error(wrapped)
    assert result.code == code
    assert result.retryable
    assert "secret" not in result.message


def test_empty_model_output_is_distinct_from_timeout():
    error = GeneralQuestionResponseError("ReAct Agent returned no messages")
    assert public_agent_error(error).code == "AGENT_RESULT_INVALID"
    error.__cause__ = TimeoutError("private")
    assert public_agent_error(error).code == "AGENT_TIMEOUT"
