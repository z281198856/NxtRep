import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain.tools import tool
from pydantic import ValidationError

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.agents.tools.journal import argument_fingerprint
from nxtrep_backend.agents.tools.nutrition import build_food_catalog_draft_tools
from nxtrep_backend.agents.tools.registry import TOOL_GROUP_BUILDERS, build_tools
from nxtrep_backend.schemas.nutrition import CustomFoodPatchRequest
from nxtrep_backend.services.nutrition import NutritionConflictError


def context() -> AgentToolContext:
    return AgentToolContext(
        user_id=uuid4(),
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=MagicMock(),
        workout_service=MagicMock(),
        nutrition_service=MagicMock(),
        body_service=MagicMock(),
        confirmation_service=MagicMock(),
        memory_service=MagicMock(),
    )


def register(monkeypatch, builder, ctx):
    monkeypatch.setitem(TOOL_GROUP_BUILDERS, "review", builder)
    return {item.name: item for item in build_tools(ctx, groups={"review"})}


def confirmation(identifier=None):
    return {
        "status": "confirmation_required",
        "confirmation": {
            "confirmation_id": str(identifier or uuid4()),
            "operation_type": "nutrition_entry_create",
            "status": "pending",
            "version": 1,
        },
    }


@pytest.mark.asyncio
async def test_successful_side_effect_replays_across_rebuilt_agent_and_context_replace(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal, notes: str | None = None) -> dict:
            """Create a meal approval for gateway regression testing."""
            calls.append((amount_g, notes))
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context()
    first = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    result = await first.ainvoke({"amount_g": "100.00"})
    rebuilt = register(monkeypatch, builder, replace(ctx))["propose_nutrition_entry"]
    replay = await rebuilt.ainvoke({"notes": None, "amount_g": "100"})
    assert replay == result
    assert len(calls) == 1
    replay["confirmation"]["version"] = 999
    assert (await rebuilt.ainvoke({"amount_g": 100}))["confirmation"]["version"] == 1
    assert ctx.journal.snapshot()["confirmation_refs"] == [
        result["confirmation"]["confirmation_id"]
    ]


@pytest.mark.asyncio
async def test_changed_arguments_create_a_distinct_proposal(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal, notes: str | None = None) -> dict:
            """Create a meal approval for gateway regression testing."""
            calls.append((amount_g, notes))
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    a = await current.ainvoke({"amount_g": 100, "notes": "原份量"})
    b = await current.ainvoke({"amount_g": 120, "notes": "纠正份量"})
    assert a["confirmation"]["confirmation_id"] != b["confirmation"]["confirmation_id"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_reads_are_fresh_and_no_progress_guard_resets_after_a_real_side_effect(monkeypatch):
    reads = []
    version = 1

    def builder(_ctx):
        @tool
        async def read_nutrition_entries(day: str) -> dict:
            """Read actual meal data each time rather than cache it."""
            reads.append(day)
            return {"status": "available", "entries": [{"version": version}]}

        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Create a meal approval for gateway regression testing."""
            nonlocal version
            version += 1
            return confirmation()

        return [read_nutrition_entries, propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)
    read = current["read_nutrition_entries"]
    assert (await read.ainvoke({"day": "today"}))["entries"][0]["version"] == 1
    assert (await read.ainvoke({"day": "today"}))["entries"][0]["version"] == 1
    await read.ainvoke({"day": "today"})
    blocked = await read.ainvoke({"day": "today"})
    assert blocked["status"] == "needs_review"
    assert blocked["error_code"] == "TOOL_NO_PROGRESS_LIMIT"
    assert len(reads) == 3
    await current["propose_nutrition_entry"].ainvoke({"amount_g": 100})
    assert (await read.ainvoke({"day": "today"}))["status"] == "available"
    assert len(reads) == 4


@pytest.mark.asyncio
async def test_total_tool_budget_blocks_new_calls_but_keeps_a_known_success(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Create a meal approval for gateway regression testing."""
            calls.append(amount_g)
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context()
    ctx.journal.max_tool_calls = 2
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    original = await current.ainvoke({"amount_g": 100})
    await current.ainvoke({"amount_g": 120})
    blocked = await current.ainvoke({"amount_g": 140})
    assert blocked["error_code"] == "TOOL_CALL_LIMIT"
    assert await current.ainvoke({"amount_g": 100}) == original
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_needs_review_and_known_business_failures_are_not_cached_or_unknown(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Fail with explicit business conditions rather than unknown side effects."""
            calls.append(amount_g)
            if amount_g == 100:
                return {"status": "needs_review", "message": "请补充克数"}
            raise NutritionConflictError("记录版本变化")

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    for _ in range(2):
        assert (await current.ainvoke({"amount_g": 100}))["status"] == "needs_review"
        with pytest.raises(NutritionConflictError):
            await current.ainvoke({"amount_g": 120})
    assert len(calls) == 4
    assert ctx.journal.snapshot()["unknown_operations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), RuntimeError(),
                                   asyncio.CancelledError()])
async def test_unknown_side_effect_outcome_cannot_be_blindly_repeated(monkeypatch, error):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Simulate interruption after a side effect may have started."""
            calls.append(amount_g)
            raise error

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    with pytest.raises(type(error)):
        await current.ainvoke({"amount_g": 100})
    rebuilt = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    result = await rebuilt.ainvoke({"amount_g": 100})
    assert result["status"] == "needs_review"
    assert result["error_code"] == "TOOL_OUTCOME_UNKNOWN"
    assert len(calls) == 1
    assert len(ctx.journal.snapshot()["unknown_operations"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name,status", [("save_memory", "saved"), ("update_memory", "updated"),
                                         ("delete_memory", "deleted"),
                                         ("cancel_confirmation", "cancelled")])
async def test_direct_write_tools_share_the_same_success_protection(monkeypatch, name, status):
    calls = []
    identifier = str(uuid4())

    async def command(expected_version: int = 1) -> dict:
        """Execute a direct write for gateway regression testing."""
        calls.append(expected_version)
        if name == "cancel_confirmation":
            return {"status": status, "confirmation": {
                "confirmation_id": identifier, "status": status, "version": 2,
                "operation_type": "nutrition_entry_create"}}
        return {"status": status, "memory_id": identifier, "version": 2}

    def builder(_ctx):
        return [tool(name)(command)]
    ctx = context()
    current = register(monkeypatch, builder, ctx)[name]
    first = await current.ainvoke({})
    rebuilt = register(monkeypatch, builder, ctx)[name]
    assert await rebuilt.ainvoke({}) == first
    assert calls == [1]


@pytest.mark.asyncio
async def test_journal_snapshot_omits_private_arguments(monkeypatch):
    identifier = uuid4()

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(notes: str) -> dict:
            """Create a meal approval with private arguments for gateway regression testing."""
            return {**confirmation(identifier), "draft": {"notes": notes}}

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    await current.ainvoke({"notes": "私密用户输入-test-token-value"})
    snapshot = ctx.journal.snapshot()
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["confirmation_refs"] == [str(identifier)]
    assert len(snapshot["operations"][0]["argument_fingerprint"]) == 64
    assert snapshot["operations"][0]["tool_call_id"]
    assert "私密" not in serialized and "test-token-value" not in serialized
    assert "draft" not in serialized and "arguments" not in serialized
    snapshot["confirmation_refs"].clear()
    assert ctx.journal.snapshot()["confirmation_refs"] == [str(identifier)]


@pytest.mark.asyncio
async def test_parallel_identical_proposals_only_execute_one_service_call(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Create a serialized proposal for gateway regression testing."""
            calls.append(amount_g)
            await asyncio.sleep(0)
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    a, b = await asyncio.gather(current.ainvoke({"amount_g": 100}),
                                current.ainvoke({"amount_g": "100.0"}))
    assert a == b and len(calls) == 1


@pytest.mark.asyncio
async def test_schema_validation_rejects_bad_arguments_before_any_business_call(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Create a proposal only for typed arguments."""
            calls.append(amount_g)
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    with pytest.raises(ValidationError):
        await current.ainvoke({"amount_g": "not-a-number"})
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, "创建成功", {}, {"status": "completed"},
                                   {"status": "confirmation_required", "confirmation": {}}])
async def test_invalid_write_result_cannot_report_success_or_repeat_the_write(monkeypatch, result):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Return a broken result after an operation might have executed."""
            calls.append(amount_g)
            return result

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    response = await current.ainvoke({"amount_g": 100})
    assert response["status"] == "needs_review" and response["error_code"] == "TOOL_RESULT_INVALID"
    assert (await current.ainvoke({"amount_g": 100}))["error_code"] == "TOOL_OUTCOME_UNKNOWN"
    assert calls == [Decimal(100)]


@pytest.mark.asyncio
async def test_incomplete_write_result_keeps_valid_uuid_for_database_recovery(monkeypatch):
    identifier = str(uuid4())

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Return a real card reference but an incomplete result envelope."""
            return {"status": "confirmation_required", "confirmation": {
                "confirmation_id": identifier}}

        return [propose_nutrition_entry]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    assert (await current.ainvoke({"amount_g": 100}))["error_code"] == "TOOL_RESULT_INVALID"
    assert ctx.journal.snapshot()["confirmation_refs"] == [identifier]


@pytest.mark.asyncio
async def test_observed_read_changes_allow_progress_but_timestamps_do_not(monkeypatch):
    calls = 0
    changing = True

    def builder(_ctx):
        @tool
        async def read_nutrition_entries(day: str) -> dict:
            """Read changes should not be classified as no progress."""
            nonlocal calls
            calls += 1
            return {"status": "available", "entries": [{"version": calls if changing else 1}],
                    "queried_at": f"clock-{calls}"}

        return [read_nutrition_entries]

    ctx = context()
    current = register(monkeypatch, builder, ctx)["read_nutrition_entries"]
    for _ in range(6):
        assert (await current.ainvoke({"day": "changing"}))["status"] == "available"
    changing = False
    for _ in range(3):
        assert (await current.ainvoke({"day": "stable"}))["status"] == "available"
    assert (await current.ainvoke({"day": "stable"}))["error_code"] == "TOOL_NO_PROGRESS_LIMIT"


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [False, True])
async def test_cancelled_or_replaced_card_cannot_replay_a_stale_pending_proposal(
    monkeypatch, replacement,
):
    identifier = str(uuid4())
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: Decimal) -> dict:
            """Create the original proposal for invalidation testing."""
            calls.append(amount_g)
            return confirmation(identifier)

        @tool
        async def cancel_confirmation(confirmation_id: str, expected_version: int) -> dict:
            """Cancel the selected draft using the existing operation pattern."""
            card = confirmation(confirmation_id)["confirmation"]
            card.update(status="cancelled", version=2)
            return {"status": "cancelled", "confirmation": card}

        @tool
        async def propose_nutrition_entry_revision(confirmation_id: str, amount_g: Decimal) -> dict:
            """Replace the selected draft while retaining its reference."""
            result = confirmation()
            result["confirmation"]["after"] = {"replaces_confirmation_id": confirmation_id}
            return result

        return [propose_nutrition_entry, cancel_confirmation, propose_nutrition_entry_revision]

    ctx = context()
    current = register(monkeypatch, builder, ctx)
    await current["propose_nutrition_entry"].ainvoke({"amount_g": 100})
    if replacement:
        await current["propose_nutrition_entry_revision"].ainvoke({
            "confirmation_id": identifier, "amount_g": 120})
    else:
        await current["cancel_confirmation"].ainvoke({
            "confirmation_id": identifier, "expected_version": 1})
    replay = await current["propose_nutrition_entry"].ainvoke({"amount_g": 100})
    assert replay["error_code"] == "TOOL_RESULT_STALE"
    assert replay["current_status"] == ("rejected" if replacement else "cancelled")
    assert calls == [Decimal(100)]


def actual_card(food):
    return SimpleNamespace(id=uuid4(), operation_type="food_create", status="pending", before=None,
                           after={"food": food.model_dump(mode="json")}, impact="新增自定义食品",
                           expires_at=datetime.now(UTC), version=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_real_food_builder_does_not_reuse_old_nutrients_for_same_name(monkeypatch, wrapped):
    ctx = context()
    ctx.nutrition_service.propose_custom_food = AsyncMock(
        side_effect=lambda **kwargs: actual_card(kwargs["body"])
    )
    tools = (
        {item.name: item for item in build_tools(ctx, groups={"food_catalog_draft"})}
        if wrapped else {item.name: item for item in build_food_catalog_draft_tools(ctx)}
    )
    food = {"name": "验收牛奶", "brand": "验收品牌", "basis_amount_g": 100,
            "kcal": 70, "protein_g": 3, "carbs_g": 4, "fat_g": 4,
            "source": "model_estimated", "confidence": "low", "notes": "暂定估算"}
    first = await tools["propose_custom_food"].ainvoke({"food": food})
    changed = await tools["propose_custom_food"].ainvoke({"food": {**food, "kcal": 75}})
    assert first["confirmation"]["confirmation_id"] != changed["confirmation"]["confirmation_id"]
    assert Decimal(changed["draft"]["kcal"]) == 75
    assert ctx.nutrition_service.propose_custom_food.await_count == 2


@pytest.mark.asyncio
async def test_real_food_update_builder_keys_the_complete_patch():
    ctx = context()
    identifier = uuid4()
    ctx.nutrition_service.get_custom_food = AsyncMock(return_value=(
        SimpleNamespace(id=identifier), SimpleNamespace(version=1)))
    ctx.nutrition_service.custom_food_snapshot.return_value = {"name": "验收牛奶"}

    def proposal(**kwargs):
        return actual_card(kwargs["patch"])

    ctx.nutrition_service.propose_custom_food_change = AsyncMock(side_effect=proposal)
    tools = {item.name: item for item in build_food_catalog_draft_tools(ctx)}
    await tools["read_custom_food"].ainvoke({"food_id": str(identifier)})
    args = {"food_id": str(identifier), "expected_version": 1}
    first = await tools["propose_custom_food_update"].ainvoke({
        **args, "changes": {"kcal": 75, "notes": "修正营养"}})
    changed = await tools["propose_custom_food_update"].ainvoke({
        **args, "changes": {"kcal": 80, "notes": "修正营养"}})
    assert first["confirmation"]["confirmation_id"] != changed["confirmation"]["confirmation_id"]
    assert Decimal(changed["draft"]["kcal"]) == 80
    assert ctx.nutrition_service.propose_custom_food_change.await_count == 2


def test_patch_fingerprint_distinguishes_preserving_and_clearing_optional_fields():
    preserve = CustomFoodPatchRequest(kcal=75, notes="修正营养")
    clear = CustomFoodPatchRequest(kcal=75, notes="修正营养", brand=None)
    assert preserve.model_dump() == clear.model_dump()
    assert argument_fingerprint({"patch": preserve}) != argument_fingerprint({"patch": clear})


@pytest.mark.asyncio
async def test_real_wrapped_food_update_does_not_confuse_omitted_brand_with_explicit_null():
    ctx = context()
    identifier = uuid4()
    ctx.nutrition_service.get_custom_food = AsyncMock(return_value=(
        SimpleNamespace(id=identifier), SimpleNamespace(version=1)))
    ctx.nutrition_service.custom_food_snapshot.return_value = {"name": "验收牛奶"}
    ctx.nutrition_service.propose_custom_food_change = AsyncMock(
        side_effect=lambda **kwargs: actual_card(kwargs["patch"]))
    tools = {item.name: item for item in build_tools(ctx, groups={"food_catalog_draft"})}
    await tools["read_custom_food"].ainvoke({"food_id": str(identifier)})
    args = {"food_id": str(identifier), "expected_version": 1}
    first = await tools["propose_custom_food_update"].ainvoke({
        **args, "changes": {"kcal": 75, "notes": "修正营养"}})
    clear = await tools["propose_custom_food_update"].ainvoke({
        **args, "changes": {"kcal": 75, "notes": "修正营养", "brand": None}})
    assert first["confirmation"]["confirmation_id"] != clear["confirmation"]["confirmation_id"]
    calls = ctx.nutrition_service.propose_custom_food_change.await_args_list
    assert "brand" not in calls[0].kwargs["patch"].model_fields_set
    assert "brand" in calls[1].kwargs["patch"].model_fields_set
    assert len(calls) == 2
