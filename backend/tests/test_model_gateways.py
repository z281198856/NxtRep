import pytest
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.models import (
    ConfiguredTextModelGateway,
    GlmVisionModelGateway,
    ModelConfigurationError,
    build_fallback_intent_router_model,
    build_fallback_text_model,
    build_fallback_vision_model,
    build_intent_router_model,
)


def test_deepseek_is_the_default_text_gateway() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("test-deepseek-key"),
        deepseek_model="deepseek-v4-flash",
    )

    model = ConfiguredTextModelGateway(settings).build()

    assert isinstance(model, ChatDeepSeek)
    assert model.model_name == "deepseek-v4-flash"
    assert model.temperature == 0.2
    assert model.extra_body == {"thinking": {"type": "disabled"}}
    assert "test-deepseek-key" not in repr(model)


def test_deepseek_thinking_mode_can_be_enabled_explicitly() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("test-deepseek-key"),
        deepseek_thinking_enabled=True,
    )

    model = ConfiguredTextModelGateway(settings).build()

    assert model.extra_body == {"thinking": {"type": "enabled"}}


def test_glm_can_be_selected_as_text_gateway() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="glm",
        glm_api_key=SecretStr("test-glm-key"),
        glm_model="glm-5.1",
    )

    model = ConfiguredTextModelGateway(settings).build()

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "glm-5.1"
    assert model.temperature == 0.2
    assert "test-glm-key" not in repr(model)


@pytest.mark.parametrize("provider", ["deepseek", "glm"])
def test_text_gateway_uses_explicit_proxy_configuration(provider: str) -> None:
    settings = Settings(
        _env_file=None,
        llm_provider=provider,
        deepseek_api_key=SecretStr("test-deepseek-key"),
        glm_api_key=SecretStr("test-glm-key"),
        llm_proxy_url="http://127.0.0.1:10808",
    )

    model = ConfiguredTextModelGateway(settings).build()

    assert model.openai_proxy == "http://127.0.0.1:10808/"


def test_glm_vision_gateway_is_independent_from_text_provider() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        glm_api_key=SecretStr("test-glm-key"),
        glm_vision_model="glm-4.6v-flash",
    )

    model = GlmVisionModelGateway(settings).build()

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "glm-4.6v-flash"
    assert model.temperature == 0.1
    assert model.max_retries == 1


def test_fallback_vision_gateway_uses_configured_free_model() -> None:
    settings = Settings(
        _env_file=None,
        glm_api_key=SecretStr("test-glm-key"),
        glm_vision_model="glm-4.6v-flash",
        glm_vision_fallback_model="glm-4v-flash",
    )

    model = build_fallback_vision_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "glm-4v-flash"
    assert model.max_retries == 1


def test_fallback_vision_gateway_is_disabled_for_duplicate_model() -> None:
    settings = Settings(
        _env_file=None,
        glm_api_key=SecretStr("test-glm-key"),
        glm_vision_model="glm-4.6v-flash",
        glm_vision_fallback_model="glm-4.6v-flash",
    )

    assert build_fallback_vision_model(settings) is None


def test_fallback_gateway_uses_the_other_configured_provider() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key=SecretStr("test-deepseek-key"),
        glm_api_key=SecretStr("test-glm-key"),
        glm_model="glm-5.1",
    )

    model = build_fallback_text_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "glm-5.1"


def test_fallback_gateway_is_optional() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key=SecretStr("test-deepseek-key"),
        glm_api_key=None,
    )

    assert build_fallback_text_model(settings) is None


def test_intent_router_gateway_uses_independent_fail_fast_policy() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("test-deepseek-key"),
        llm_timeout_seconds=45,
        llm_max_retries=2,
    )

    regular_model = ConfiguredTextModelGateway(settings).build()
    router_model = build_intent_router_model(settings)

    assert regular_model.request_timeout == 45
    assert regular_model.max_retries == 2
    assert router_model.request_timeout == 12
    assert router_model.max_retries == 0


def test_fallback_intent_router_gateway_uses_other_provider_and_router_policy() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key=SecretStr("test-deepseek-key"),
        glm_api_key=SecretStr("test-glm-key"),
        glm_model="glm-5.1",
        llm_timeout_seconds=45,
        llm_max_retries=2,
        agent_intent_router_timeout_seconds=9,
        agent_intent_router_max_retries=0,
    )

    model = build_fallback_intent_router_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "glm-5.1"
    assert model.request_timeout == 9
    assert model.max_retries == 0


def test_fallback_intent_router_gateway_is_optional() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key=SecretStr("test-deepseek-key"),
        glm_api_key=None,
    )

    assert build_fallback_intent_router_model(settings) is None


@pytest.mark.parametrize(
    ("gateway", "expected_key"),
    [
        (
            lambda: ConfiguredTextModelGateway(
                Settings(_env_file=None, llm_provider="deepseek", deepseek_api_key=None)
            ),
            "NXTREP_DEEPSEEK_API_KEY",
        ),
        (
            lambda: ConfiguredTextModelGateway(
                Settings(_env_file=None, llm_provider="glm", glm_api_key=None)
            ),
            "NXTREP_GLM_API_KEY",
        ),
        (
            lambda: GlmVisionModelGateway(Settings(_env_file=None, glm_api_key=None)),
            "NXTREP_GLM_API_KEY",
        ),
    ],
)
def test_model_gateways_report_missing_provider_key(gateway: object, expected_key: str) -> None:
    with pytest.raises(ModelConfigurationError, match=expected_key):
        gateway().build()
