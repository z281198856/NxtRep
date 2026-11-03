from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from nxtrep_backend.core.config import Settings
from nxtrep_backend.db.models import AgentConversation
from nxtrep_backend.providers.models import build_conversation_title_model
from nxtrep_backend.services.conversation_title import (
    ModelConversationTitler,
    needs_conversation_title,
)


@pytest.mark.asyncio
async def test_title_is_based_on_messages_without_internal_memory_or_tools():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content="“午饭份量与脂肪调整”")
    messages = [{"role": "user", "content": "午饭这份脂肪偏高，调低一点"}]
    title = await ModelConversationTitler(model).generate(messages)
    assert title == "午饭份量与脂肪调整"
    prompt = model.ainvoke.call_args.args[0]
    assert "午饭这份脂肪偏高" in prompt[1].content
    assert "只输出一行标题" in prompt[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ["", "a", "过长" * 30, "标题\n说明", "https://example.test"])
async def test_invalid_model_title_is_not_saved_as_summary(output):
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=output)
    with pytest.raises(ValueError):
        await ModelConversationTitler(model).generate([])


@pytest.mark.parametrize(
    "title,source,sequence,through,expected",
    [
        (None, "legacy", 1, 0, False),
        (None, "legacy", 3, 0, True),
        ("训练咨询", "legacy", 3, 0, True),
        ("我的命名", "legacy", 30, 0, False),
        ("训练咨询", "manual", 30, 0, False),
        ("午饭估算", "generated", 9, 2, False),
        ("午饭估算", "generated", 15, 2, True),
        ("帮我记午饭", "fallback", 3, 0, True),
    ],
)
def test_manual_titles_are_preserved_and_empty_chats_do_not_call_model(
    title,
    source,
    sequence,
    through,
    expected,
):
    item = AgentConversation(
        id=uuid4(),
        title=title,
        title_source=source,
        next_sequence=sequence,
        title_through_sequence=through,
    )
    assert needs_conversation_title(item) is expected


def test_title_model_is_independent_fast_and_optional():
    settings = Settings(
        _env_file=None,
        glm_api_key=SecretStr("unit-test-key"),
        glm_model="glm-5.1",
        conversation_title_model="glm-4.7-flash",
    )
    model = build_conversation_title_model(settings)
    assert model.model_name == "glm-4.7-flash"
    assert model.max_retries == 0
    assert model.request_timeout == 8
    assert model.extra_body == {"thinking": {"type": "disabled"}}
    assert build_conversation_title_model(Settings(_env_file=None)) is None


@pytest.mark.asyncio
async def test_invalid_title_has_only_one_output_validation_retry():
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(content="过长的回复" * 10),
        AIMessage(content="午饭份量调整"),
    ]
    assert await ModelConversationTitler(model).generate([]) == "午饭份量调整"
    assert model.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_useful_multi_topic_title_is_not_rejected_by_a_rigid_short_limit():
    title = "史密斯上斜推胸训练记录和午饭营养份量调整与日期更正"
    assert 24 < len(title) <= 40
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=title)
    assert await ModelConversationTitler(model).generate([]) == title
    assert model.ainvoke.await_count == 1
