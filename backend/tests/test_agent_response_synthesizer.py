import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from test_nutrition_record_draft_branch_handler import make_analysis

from nxtrep_backend.agents.synthesis import (
    AgentResponseSynthesisError,
    AgentResponseSynthesizer,
)
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentCitation,
    AgentConfirmationCard,
    AgentExecutionBundle,
)


def test_search_appendix_does_not_turn_the_first_unused_candidate_into_a_source():
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "有用回答。"},
                citations=[
                    AgentCitation(
                        source_type="web",
                        source_id=f"https://example.org/{index}",
                        label="研究 / 查询时间 2026-10-05T10:00:00+00:00",
                    )
                    for index in range(3)
                ],
            )
        ]
    )
    suffix = AgentResponseSynthesizer._web_source_suffix("有用回答。", bundle)
    assert suffix == ""
    bundle.branch_results[0].result["answer"] = "依据第二条资料：https://example.org/1"
    assert AgentResponseSynthesizer._web_source_suffix("有用回答。", bundle) == (
        "\n\n[来源](https://example.org/1)"
    )
    assert AgentResponseSynthesizer._web_source_suffix("参考https://example.org/2", bundle) == ""


def make_execution_bundle() -> AgentExecutionBundle:
    body_asset_id = uuid4()
    food_asset_id = uuid4()

    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_assessment",
                asset_ids=[body_asset_id],
                status="completed",
                result={
                    "summary": "Shoulder height may be asymmetric",
                },
            ),
            AgentBranchResult(
                task_type="nutrition_analysis",
                asset_ids=[food_asset_id],
                status="completed",
                result={
                    "foods": ["rice", "chicken"],
                    "estimated_kcal": 520,
                },
                requires_confirmation=True,
            ),
        ],
        clarification_questions=[
            "How much cooking oil was used?",
        ],
    )


def make_model(response: AIMessage) -> MagicMock:
    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock(return_value=response)
    return model


@pytest.mark.asyncio
async def test_text_meal_reply_keeps_actual_card_totals_when_nested_context_is_trimmed():
    model = make_model(AIMessage(content="这餐估算约923千卡。"))
    total = {"kcal": "923.4", "protein_g": "41", "carbs_g": "56", "fat_g": "11"}
    bundle = AgentExecutionBundle(branch_results=[AgentBranchResult(
        task_type="nutrition_record_draft", status="completed", requires_confirmation=True,
        result={"task_tool_results": [{"irrelevant": "x" * 20000}]},
        confirmation_cards=[AgentConfirmationCard(
            confirmation_id=uuid4(), operation_type="nutrition_entry_create", status="pending",
            version=1, expires_at="2026-10-19T00:00:00Z", impact="确认后保存",
            after={"preview": {"totals": total, "items": [{"name": "米饭", "amount_g": "200"}]}},
        )],
    )])
    await AgentResponseSynthesizer(model).synthesize(
        user_message="记录午饭", execution_bundle=bundle,
    )
    payload = json.loads(model.ainvoke.await_args.args[0][1].content)
    actual = next(
        item for item in payload["photo_nutrition_evidence"] if item.get("confirmation_preview")
    )
    assert actual["totals"] == total
    assert actual["foods"][0]["amount_g"] == "200"


def make_stream_model(*chunks: str, error: Exception | None = None) -> MagicMock:
    model = MagicMock(spec=BaseChatModel)

    async def stream(_messages):
        for chunk in chunks:
            yield AIMessageChunk(content=chunk)
        if error is not None:
            raise error

    model.astream = MagicMock(side_effect=stream)
    return model


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("already_visible", [True, False])
async def test_actual_search_sources_remain_visible_in_sync_and_streaming_answer(
    streaming,
    already_visible,
):
    url = "https://example.com/actual-search-source"
    text = "根据资料回答。" + (url if already_visible else "")
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "根据资料回答。" + url},
                citations=[
                    AgentCitation(
                        source_type="web", source_id=url, label="来源 / 查询时间 2026-10-05"
                    )
                ],
            )
        ]
    )
    model = (
        make_stream_model(text[:10], text[10:])
        if streaming
        else make_model(AIMessage(content=text))
    )
    synthesizer = AgentResponseSynthesizer(model)
    if streaming:
        result = "".join(
            [
                part
                async for part in synthesizer.astream(
                    user_message="普通知识提问",
                    execution_bundle=bundle,
                )
            ]
        )
    else:
        result = await synthesizer.synthesize(user_message="普通知识提问", execution_bundle=bundle)
    assert result.count(url) == 1
    assert ("[来源]" in result) is (not already_visible)
    assert "查询时间" not in result


@pytest.mark.asyncio
async def test_synthesizer_sends_all_branch_results_to_text_model() -> None:
    model = make_model(
        AIMessage(
            content=("这顿饭估算约 520 千卡；图片估算存在误差，请确认食物份量和用油量后再保存。")
        )
    )
    bundle = make_execution_bundle()
    synthesizer = AgentResponseSynthesizer(model)

    result = await synthesizer.synthesize(
        user_message="分析我的体态和这顿饭",
        execution_bundle=bundle,
    )

    assert result.endswith("再保存。")
    model.ainvoke.assert_awaited_once()
    messages = model.ainvoke.await_args.args[0]

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "Memory 已经生效" in messages[0].content
    assert "其他正式业务数据不得声称已保存" in messages[0].content
    assert "把理由和分析融入正文" in messages[0].content
    assert "未核验数值不得冒充官方数据" in messages[0].content
    assert "unpersisted_suggestion" in messages[0].content
    assert "旧回复声称没有资料不能覆盖本轮已读取的资料" in messages[0].content
    assert "Markdown 表格" in messages[0].content

    payload = json.loads(messages[1].content)
    assert payload["user_message"] == "分析我的体态和这顿饭"
    assert len(payload["execution_bundle"]["branch_results"]) == 2
    nutrition_result = payload["execution_bundle"]["branch_results"][1]
    assert nutrition_result["requires_confirmation"] is True
    assert payload["execution_bundle"]["clarification_questions"] == [
        "How much cooking oil was used?"
    ]


@pytest.mark.asyncio
async def test_synthesizer_strips_model_response() -> None:
    model = make_model(AIMessage(content="  请补充一张清晰的食物图片。  "))
    synthesizer = AgentResponseSynthesizer(model)

    result = await synthesizer.synthesize(
        user_message="分析饮食",
        execution_bundle=make_execution_bundle(),
    )

    assert result == "请补充一张清晰的食物图片。"


@pytest.mark.asyncio
async def test_synthesizer_rejects_empty_model_response() -> None:
    model = make_model(AIMessage(content="   "))
    synthesizer = AgentResponseSynthesizer(model)

    with pytest.raises(
        AgentResponseSynthesisError,
        match="empty response",
    ):
        await synthesizer.synthesize(
            user_message="分析饮食",
            execution_bundle=make_execution_bundle(),
        )


@pytest.mark.asyncio
async def test_synthesizer_uses_fallback_when_primary_fails() -> None:
    primary = make_model(AIMessage(content="unused"))
    primary.ainvoke.side_effect = TimeoutError("primary timeout")
    fallback = make_model(AIMessage(content="备用模型回答"))

    result = await AgentResponseSynthesizer(primary, fallback).synthesize(
        user_message="分析饮食",
        execution_bundle=make_execution_bundle(),
    )

    assert result == "备用模型回答"
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_synthesizer_streams_native_model_deltas_without_buffering_answer() -> None:
    release_remainder = asyncio.Event()
    model = MagicMock(spec=BaseChatModel)

    async def stream(_messages):
        yield AIMessageChunk(content="  你")
        await release_remainder.wait()
        yield AIMessageChunk(content="好")
        yield AIMessageChunk(content=" ")
        yield AIMessageChunk(content="呀  ")

    model.astream = MagicMock(side_effect=stream)
    synthesizer = AgentResponseSynthesizer(model)

    stream = synthesizer.astream(
        user_message="给我建议",
        execution_bundle=make_execution_bundle(),
    )

    assert await asyncio.wait_for(anext(stream), timeout=0.1) == "你"
    assert not release_remainder.is_set()
    release_remainder.set()
    assert [item async for item in stream] == ["好", " 呀"]
    model.astream.assert_called_once()
    assert len(model.astream.call_args.args[0]) == 2


@pytest.mark.asyncio
async def test_synthesizer_stream_falls_back_only_before_output_starts() -> None:
    primary = make_stream_model(error=TimeoutError("primary timeout"))
    fallback = make_stream_model("备用", "回答")
    synthesizer = AgentResponseSynthesizer(primary, fallback)

    chunks = [
        item
        async for item in synthesizer.astream(
            user_message="给我建议",
            execution_bundle=make_execution_bundle(),
        )
    ]

    assert chunks == ["备用", "回答"]
    primary.astream.assert_called_once()
    fallback.astream.assert_called_once()


@pytest.mark.asyncio
async def test_synthesizer_stream_never_splices_fallback_after_partial_output() -> None:
    primary = make_stream_model("部分", error=TimeoutError("stream interrupted"))
    fallback = make_stream_model("不应出现")
    synthesizer = AgentResponseSynthesizer(primary, fallback)
    stream = synthesizer.astream(
        user_message="给我建议",
        execution_bundle=make_execution_bundle(),
    )

    assert await anext(stream) == "部分"
    with pytest.raises(AgentResponseSynthesisError, match="after output started"):
        await anext(stream)
    fallback.astream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("task_type", ["nutrition_analysis", "nutrition_record_draft"])
async def test_photo_totals_portions_and_uncertainty_survive_deep_and_large_context(
    streaming, task_type
):
    analysis = make_analysis()
    analysis.calculation.requires_confirmation = True
    analysis.recognition.assumptions = ["照片份量没有称重"]
    analysis.calculation.items[0].assumptions = ["按常见做法估算用油"]
    analysis.calculation.items[0].source = "model_estimated"
    analysis.calculation.items[0].confidence = "low"
    actual = analysis.model_dump(mode="json")
    branch_result = actual if task_type == "nutrition_analysis" else {"analysis": actual}
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question", status="completed", result={"answer": "旧信息" * 9000}
            ),
            AgentBranchResult(task_type=task_type, status="completed", result=branch_result),
        ]
    )
    before = bundle.model_dump(mode="json")
    model = (
        make_stream_model("按照片估算。")
        if streaming
        else make_model(AIMessage(content="按照片估算。"))
    )
    synthesizer = AgentResponseSynthesizer(model)
    if streaming:
        _ = [
            chunk
            async for chunk in synthesizer.astream(user_message="评估午饭", execution_bundle=bundle)
        ]
        messages = model.astream.call_args.args[0]
    else:
        await synthesizer.synthesize(user_message="评估午饭", execution_bundle=bundle)
        messages = model.ainvoke.call_args.args[0]
    context = json.loads(messages[1].content)
    evidence = context["photo_nutrition_evidence"][0]
    assert evidence["branch_index"] == 1 and evidence["is_complete"] is True
    assert evidence["totals"] == actual["calculation"]["totals"]
    assert evidence["foods"] == actual["recognition"]["foods"]
    assert evidence["estimate_needs_review"] is True
    assert evidence["nutrition_sources"] == ["model_estimated"]
    assert evidence["nutrition_confidence"] == ["low"]
    assert evidence["assumptions"] == ["照片份量没有称重", "按常见做法估算用油"]
    assert (
        len(
            json.dumps(
                {key: context[key] for key in ("execution_bundle", "photo_nutrition_evidence")},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        <= 8000
    )
    assert bundle.model_dump(mode="json") == before


@pytest.mark.parametrize("status", ["needs_input", "failed"])
def test_partial_or_failed_photo_result_is_never_projected_as_complete(status):
    analysis = make_analysis()
    analysis.calculation.is_complete = False
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="nutrition_analysis",
                status=status,
                missing_fields=["food_selection"],
                result=analysis.model_dump(mode="json") if status != "failed" else None,
                error={"code": "FOOD_ANALYSIS_FAILED", "message": "本次照片分析未完成"}
                if status == "failed"
                else None,
            )
        ]
    )
    messages = AgentResponseSynthesizer._messages(
        user_message="评估午饭", execution_bundle=bundle, conversation_context=None
    )
    context = json.loads(messages[1].content)
    if status == "failed":
        assert "photo_nutrition_evidence" not in context
    else:
        assert context["photo_nutrition_evidence"][0]["is_complete"] is False
