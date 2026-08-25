from uuid import UUID

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from nxtrep_backend.agents.prompts import SYSTEM_PROMPT
from nxtrep_backend.agents.tools import build_read_tools
from nxtrep_backend.core.config import Settings


def build_agent(settings: Settings, user_id: UUID):
    if settings.openai_api_key is None:
        raise ValueError("NXTREP_OPENAI_API_KEY is not configured")

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key.get_secret_value(),
        temperature=0.2,
        timeout=45,
        max_retries=2,
    )
    return create_agent(
        model=model,
        tools=build_read_tools(user_id),
        system_prompt=SYSTEM_PROMPT,
        name="nxtrep_coach",
    )
