import pytest
from pydantic import ValidationError

from nxtrep_backend.core.config import Settings


def test_agent_stream_intervals_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.agent_sse_heartbeat_seconds == 15
    assert settings.agent_sse_disconnect_poll_seconds == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_sse_heartbeat_seconds", 1),
        ("agent_sse_disconnect_poll_seconds", 0),
    ],
)
def test_agent_stream_intervals_reject_busy_polling(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
