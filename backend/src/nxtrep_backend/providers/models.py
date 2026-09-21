from typing import Literal, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from nxtrep_backend.core.config import Settings


class ModelConfigurationError(ValueError):
    """Raised when a selected model provider is missing required configuration."""


class TextModelGateway(Protocol):
    def build(self) -> BaseChatModel: ...


class VisionModelGateway(Protocol):
    def build(self) -> BaseChatModel: ...


class ConfiguredTextModelGateway:
    """Build the configured DeepSeek or GLM text model for Agent reasoning."""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: Literal["deepseek", "glm"] | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ):
        self._settings = settings
        self._provider = provider or settings.llm_provider
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def build(self) -> BaseChatModel:
        common_options = {
            "temperature": self._settings.llm_temperature,
            "timeout": (
                self._settings.llm_timeout_seconds
                if self._timeout_seconds is None
                else self._timeout_seconds
            ),
            "max_retries": (
                self._settings.llm_max_retries if self._max_retries is None else self._max_retries
            ),
        }
        if self._settings.llm_proxy_url is not None:
            common_options["openai_proxy"] = str(self._settings.llm_proxy_url)

        if self._provider == "deepseek":
            if self._settings.deepseek_api_key is None:
                raise ModelConfigurationError("NXTREP_DEEPSEEK_API_KEY is not configured")
            return ChatDeepSeek(
                model=self._settings.deepseek_model,
                api_key=self._settings.deepseek_api_key.get_secret_value(),
                extra_body={
                    "thinking": {
                        "type": (
                            "enabled" if self._settings.deepseek_thinking_enabled else "disabled"
                        )
                    }
                },
                **common_options,
            )

        if self._settings.glm_api_key is None:
            raise ModelConfigurationError("NXTREP_GLM_API_KEY is not configured")
        return ChatOpenAI(
            model=self._settings.glm_model,
            api_key=self._settings.glm_api_key.get_secret_value(),
            base_url=self._settings.glm_base_url,
            **common_options,
        )


class GlmVisionModelGateway:
    """Build the GLM vision model dedicated to food and body image understanding."""

    def __init__(
        self,
        settings: Settings,
        *,
        model_name: str | None = None,
    ):
        self._settings = settings
        self._model_name = model_name or settings.glm_vision_model

    def build(self) -> BaseChatModel:
        if self._settings.glm_api_key is None:
            raise ModelConfigurationError("NXTREP_GLM_API_KEY is not configured")
        options = {
            "temperature": self._settings.vision_temperature,
            "timeout": self._settings.vision_timeout_seconds,
            "max_retries": self._settings.vision_max_retries,
        }
        if self._settings.llm_proxy_url is not None:
            options["openai_proxy"] = str(self._settings.llm_proxy_url)
        return ChatOpenAI(
            model=self._model_name,
            api_key=self._settings.glm_api_key.get_secret_value(),
            base_url=self._settings.glm_base_url,
            **options,
        )


def build_text_model(settings: Settings) -> BaseChatModel:
    return ConfiguredTextModelGateway(settings).build()


def build_fallback_text_model(settings: Settings) -> BaseChatModel | None:
    """Build the other configured text provider, if its credential exists."""
    if settings.llm_provider == "deepseek":
        if settings.glm_api_key is None:
            return None
        return ConfiguredTextModelGateway(settings, provider="glm").build()
    if settings.deepseek_api_key is None:
        return None
    return ConfiguredTextModelGateway(settings, provider="deepseek").build()


def build_intent_router_model(settings: Settings) -> BaseChatModel:
    """Build the primary text model with the router's fail-fast policy."""
    return ConfiguredTextModelGateway(
        settings,
        timeout_seconds=settings.agent_intent_router_timeout_seconds,
        max_retries=settings.agent_intent_router_max_retries,
    ).build()


def build_fallback_intent_router_model(settings: Settings) -> BaseChatModel | None:
    """Build the other provider with the same fail-fast router policy, if configured."""
    if settings.llm_provider == "deepseek":
        if settings.glm_api_key is None:
            return None
        provider: Literal["deepseek", "glm"] = "glm"
    else:
        if settings.deepseek_api_key is None:
            return None
        provider = "deepseek"
    return ConfiguredTextModelGateway(
        settings,
        provider=provider,
        timeout_seconds=settings.agent_intent_router_timeout_seconds,
        max_retries=settings.agent_intent_router_max_retries,
    ).build()


def build_vision_model(settings: Settings) -> BaseChatModel:
    return GlmVisionModelGateway(settings).build()


def build_fallback_vision_model(settings: Settings) -> BaseChatModel | None:
    """Build the optional single-image fallback used when the primary pool is busy."""
    fallback = (settings.glm_vision_fallback_model or "").strip()
    if not fallback or fallback == settings.glm_vision_model:
        return None
    return GlmVisionModelGateway(settings, model_name=fallback).build()
