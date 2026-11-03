"""Opt-in real-model/API and Android acceptance using a disposable test account.

Requires an already running local API. RUN_AGENT_DEVICE_TESTS=1 additionally
uses an already running emulator and the installed Flutter SDK. No services start.
"""

import json
import os
import re
import secrets
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.core.security import hash_password
from nxtrep_backend.db.models import (
    AgentConversation,
    AgentMemory,
    BodyMeasurement,
    CalendarEvent,
    Credential,
    Food,
    NutritionEntry,
    Profile,
    User,
    UserConstraint,
    UserGoal,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.knowledge.schemas import KnowledgeRetrievalHit
from nxtrep_backend.providers.models import build_intent_router_model, build_text_model
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentIntentTask
from nxtrep_backend.schemas.nutrition import (
    FoodCreateRequest,
    NutritionEntryCreateRequest,
    NutritionItemInput,
)
from nxtrep_backend.schemas.workout import (
    WorkoutCreateRequest,
    WorkoutFinishRequest,
    WorkoutSetCreateRequest,
)
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.knowledge import (
    KnowledgeRetrievalBranchHandler,
)
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1",
    reason="Opt-in only: calls configured model and a running local API",
)
ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8000/api/v1"


@pytest.mark.asyncio(loop_scope="session")
async def test_next_round_real_model_revision_review_meal_and_recovery(live_account):
    client, user_id, _, _, _ = live_account
    results = []

    async def chat(message, **extra):
        response = await client.post("/agent/chat", json={"message": message, **extra})
        assert response.status_code == 200
        payload = response.json()
        results.append({"request": message, "response": payload})
        (ROOT / ".local" / "agent-next-round-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert payload["status"] == "completed", "Inspect agent-next-round-live.json"
        return payload

    # A deterministic initial draft keeps the acceptance focused on natural follow-up revision.
    async with SessionFactory() as session:
        nutrition = NutritionService(
            SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
        )
        old = await nutrition.propose_entry(
            user_id=user_id,
            body=NutritionEntryCreateRequest(
                meal_type="lunch",
                eaten_at=datetime.now(UTC),
                items=[
                    NutritionItemInput(
                        name="熟米饭",
                        amount_g=200,
                        basis_amount_g=100,
                        kcal=116,
                        protein_g=3,
                        carbs_g=26,
                        fat_g=1,
                        source="model_estimated",
                        confidence="low",
                    )
                ],
            ),
        )
        old_id, old_version = str(old.id), old.version
        await session.commit()
    revised = await chat(
        "把待确认的这份午餐草稿里的熟米饭改成100克，其他不变，生成新的待确认草稿。"
    )
    names = {r["tool_name"] for b in revised["analysis_results"] for r in b.get("tool_runs", [])}
    assert "propose_nutrition_entry_revision" in names
    card = revised["confirmation_cards"][0]
    assert card["after"]["replaces_confirmation_id"] == old_id
    assert Decimal(card["after"]["preview"]["totals"]["kcal"]) == 116
    old_approval = await client.post(
        f"/confirmations/{old_id}/approve",
        json={"expected_version": old_version},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert old_approval.status_code == 409
    review = await chat("请按我的真实记录复盘最近两周，与前两周比较，给三个有依据的下一步建议。")
    assert any(
        r["tool_name"] == "read_progress_review"
        for b in review["analysis_results"]
        for r in b.get("tool_runs", [])
    )
    meal = await chat(
        "按我的目标和今天已经记录的饮食，给一份晚餐搭配；按常见份量估算，计算营养，不要记账。"
    )
    assert not meal["confirmation_cards"]
    assert any(
        word in meal["message"] for word in ("米饭", "鸡胸", "豆腐", "土豆", "鸡蛋", "鱼", "牛肉")
    ), "Actual reply must show meal portions"
    assert any(
        r["tool_name"] == "calculate_meal_option"
        for b in meal["analysis_results"]
        for r in b.get("tool_runs", [])
    )
    async with SessionFactory() as session:
        event = await session.scalar(
            select(CalendarEvent)
            .where(CalendarEvent.user_id == user_id, CalendarEvent.actual_workout_id.is_(None))
            .order_by(CalendarEvent.scheduled_date)
        )
        event_day = event.scheduled_date.isoformat()
        event_id = event.id
        original_event = (event.scheduled_date, event.estimated_minutes, event.content_snapshot)
    adjustment = await chat(
        f"请把{event_day}尚未开始的训练缩短成30分钟，读取恢复记录，先生成待确认草稿，不要新建计划。"
    )
    assert any(
        r["tool_name"] == "propose_recovery_adjustment"
        for b in adjustment["analysis_results"]
        for r in b.get("tool_runs", [])
    )
    assert any(
        c["operation_type"] == "calendar_reschedule" for c in adjustment["confirmation_cards"]
    )
    assert not re.search(
        r"已(?:经)?(?:按|把|将|调整|缩短|压缩)", adjustment["message"]
    ), "Pending training changes must be phrased as a proposal, not an executed change"
    async with SessionFactory() as session:
        unchanged = await session.get(CalendarEvent, event_id)
        assert (
            unchanged.scheduled_date, unchanged.estimated_minutes, unchanged.content_snapshot
        ) == original_event
    recovery = await chat(
        "请读取我最近保存的恢复状态，判断今天是否适合照常训练，别把昨天的记录当成今天的睡眠。"
    )
    assert any(
        r["tool_name"] == "read_recovery_status"
        for b in recovery["analysis_results"]
        for r in b.get("tool_runs", [])
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_multiturn_revision_cancellation_replacement_and_brief_reply(live_account):
    client, user_id, source_date, target_date, _ = live_account
    conversation = await client.post("/agent/conversations", json={"title": "多轮任务验收"})
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    results = []

    async def chat(message):
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        results.append({"request": message, "response": payload})
        (ROOT / ".local" / "agent-multiturn-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert payload["status"] == "completed", "Inspect agent-multiturn-live.json"
        return payload

    async with SessionFactory() as session:
        service = NutritionService(
            SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
        )
        initial = await service.propose_entry(
            user_id=user_id,
            body=NutritionEntryCreateRequest(
                meal_type="lunch",
                eaten_at=datetime.now(UTC),
                items=[
                    NutritionItemInput(
                        name="熟米饭",
                        amount_g=200,
                        basis_amount_g=100,
                        kcal=116,
                        protein_g=3,
                        carbs_g=26,
                        fat_g=1,
                        source="model_estimated",
                        confidence="low",
                    )
                ],
            ),
        )
        initial_id = str(initial.id)
        await session.commit()
    meal = await chat("把待确认的这份午餐草稿里的米饭改成100克，其他不变。")
    revised = meal["confirmation_cards"][0]
    assert revised["after"]["replaces_confirmation_id"] == initial_id
    assert Decimal(revised["after"]["preview"]["totals"]["kcal"]) == 116
    advice = await chat("只用两句话解释一下，这份草稿还没保存对吗？")
    assert not advice["confirmation_cards"]
    assert any(
        run["tool_name"] in {"list_confirmations", "read_confirmation_status"}
        for branch in advice["analysis_results"]
        for run in branch["tool_runs"]
    )
    assert "没有直接修改草稿" not in advice["message"]
    cancelled = await chat("先不保存了，取消刚才这份午餐草稿。")
    assert any(
        op.get("status") == "cancelled"
        and op["confirmation"]["confirmation_id"] == revised["confirmation_id"]
        for branch in cancelled["analysis_results"]
        for op in branch["operation_results"]
    )
    shift = await chat(f"把{source_date}的训练改到{target_date}，先给草稿。")
    old = shift["confirmation_cards"][0]
    changed_date = target_date + timedelta(days=1)
    changed = await chat(f"刚才改期的草稿改到{changed_date}，原训练不变，先不要执行。")
    new = changed["confirmation_cards"][0]
    assert new["after"]["replaces_confirmation_id"] == old["confirmation_id"]
    before = await client.get(
        "/calendar",
        params={
            "start_date": source_date.isoformat(),
            "end_date": source_date.isoformat(),
        },
    )
    assert before.status_code == 200 and before.json()
    old_approval = await client.post(
        f"/confirmations/{old['confirmation_id']}/approve",
        json={"expected_version": old["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert old_approval.status_code == 409
    approval_key = str(uuid4())
    for _ in range(2):
        approved = await client.post(
            f"/confirmations/{new['confirmation_id']}/approve",
            json={"expected_version": new["version"]},
            headers={"Idempotency-Key": approval_key},
        )
        assert approved.status_code == 200
    after = await client.get(
        "/calendar",
        params={
            "start_date": changed_date.isoformat(),
            "end_date": changed_date.isoformat(),
        },
    )
    assert after.status_code == 200 and len(after.json()) == 1
    brief = await chat(
        "力量训练后有点酸痛，但没有异常疼痛。只用三句话说一般怎么安排恢复，"
        "不要复述我的个人资料，也不要修改计划。"
    )
    assert len(brief["message"]) < 500
    assert not brief["confirmation_cards"]
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == 1
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_multiturn_meal_swap_preserves_rice_recalculates_and_never_records(live_account):
    client, user_id, _, _, _ = live_account
    conversation = await client.post("/agent/conversations", json={"title": "搭配替换验收"})
    conversation_id = conversation.json()["id"]
    results = []

    async def option(message):
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        results.append({"request": message, "response": data})
        (ROOT / ".local" / "agent-meal-swap-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert data["status"] == "completed" and not data["confirmation_cards"]
        options = [
            record
            for branch in data["analysis_results"]
            for record in (branch.get("result") or {}).get("queried_records", [])
            if record["tool_name"] == "calculate_meal_option"
        ]
        assert options, "Actual nutrition recalculation required"
        return options[-1]

    original = await option(
        "按今天已有饮食和目标，给一份150克鸡胸肉加100克熟米饭的晚餐搭配，"
        "写估算营养，先不要记账，简短回答。"
    )
    swapped = await option(
        "刚才的鸡胸肉换成豆腐，蛋白质尽量接近，米饭保持100克不变，重新计算，不要记账，简短回答。"
    )
    assert any("豆腐" in item["name"] for item in swapped["items"])
    assert not any("鸡胸" in item["name"] for item in swapped["items"])
    rice = next(item for item in swapped["items"] if "米饭" in item["name"])
    assert Decimal(str(rice["amount_g"])) == 100
    assert original["meal_totals"] != swapped["meal_totals"]
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == 1
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_meal_nutrient_feedback_reads_draft_without_memory_and_explicit_revision(
    live_account,
):
    client, user_id, _, _, _ = live_account
    response = await client.post("/agent/conversations", json={"title": "营养追问回归"})
    assert response.status_code == 201
    conversation_id = UUID(response.json()["id"])
    async with SessionFactory() as session:
        service = NutritionService(
            SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
        )
        initial = await service.propose_entry(
            user_id=user_id,
            body=NutritionEntryCreateRequest(
                meal_type="lunch",
                eaten_at=datetime.now(UTC),
                items=[
                    NutritionItemInput(
                        name="熟白米饭",
                        amount_g=200,
                        basis_amount_g=100,
                        kcal=130,
                        protein_g=2.69,
                        carbs_g=28.17,
                        fat_g=0.28,
                        source="model_estimated",
                        confidence="low",
                    ),
                    NutritionItemInput(
                        name="泡椒鸡胗",
                        amount_g=150,
                        basis_amount_g=150,
                        kcal=265,
                        protein_g=28.8,
                        carbs_g=12,
                        fat_g=11,
                        source="model_estimated",
                        confidence="low",
                    ),
                ],
            ),
        )
        original_id = str(initial.id)
        repo = SqlAlchemyConversationRepository(session)
        conversation = await session.get(AgentConversation, conversation_id)
        await repo.append_message(
            conversation=conversation, role="user", content="午饭是泡脚鸡胗饭"
        )
        await repo.append_message(
            conversation=conversation,
            role="assistant",
            content=(
                "已创建午餐草稿：熟白米饭200克、泡椒鸡胗150克，碳水合计约68克。确认后才保存。"
            ),
        )
        memory_count = await session.scalar(
            select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
        )
        await session.commit()
    evidence = []

    async def chat(message):
        response = await client.post(
            "/agent/chat",
            json={
                "conversation_id": str(conversation_id),
                "message": message,
            },
        )
        assert response.status_code == 200
        data = response.json()
        evidence.append({"request": message, "response": data})
        (ROOT / ".local" / "agent-nutrient-followup-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert data["status"] == "completed", "Inspect nutrient follow-up evidence"
        assert not any(branch["task_type"] == "memory_write" for branch in data["analysis_results"])
        return data

    feedback = await chat("碳水应该不超过六十克")
    assert not feedback["confirmation_cards"]
    assert "68" in feedback["message"], "Actual draft's total must remain visible"
    assert any(
        run["tool_name"] in {"list_confirmations", "read_confirmation_status"}
        for branch in feedback["analysis_results"]
        for run in branch["tool_runs"]
    )
    old = await client.get(f"/confirmations/{original_id}")
    assert old.json()["status"] == "pending"
    changed = await chat("把米饭减少，让整餐碳水控制在60克以内，鸡胗不变，先改草稿。")
    card = changed["confirmation_cards"][0]
    assert card["after"]["replaces_confirmation_id"] == original_id
    preview = card["after"]["preview"]
    assert Decimal(preview["totals"]["carbs_g"]) <= 60
    assert Decimal(preview["items"][1]["amount_g"]) == 150
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
            )
            == memory_count
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == 1
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_gizzard_meal_finishes_with_draft_without_saving_a_meal(live_account):
    client, user_id, _, _, _ = live_account
    started = monotonic()
    response = await client.post("/agent/chat", json={"message": "今天午饭是泡椒鸡胗饭"})
    assert response.status_code == 200
    payload = response.json()
    elapsed = round(monotonic() - started, 2)
    (ROOT / ".local" / "agent-stall-meal-live.json").write_text(
        json.dumps(
            {"elapsed_seconds": elapsed, "response": payload},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert payload["status"] == "completed", "Inspect stalled-meal live evidence"
    assert elapsed < 125
    assert any(
        card["operation_type"] == "nutrition_entry_create" for card in payload["confirmation_cards"]
    )
    assert any(word in payload["message"] for word in ("鸡胗", "鸡肫"))
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == 1
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_memory_business_boundaries_with_real_router():
    router = AgentIntentRouter(build_intent_router_model(get_settings()))
    cases = [
        ("帮我在食品库添加自定义食品麦当劳的双层吉士汉堡和一个香芋派", False, "food_catalog_draft"),
        ("把午餐米饭改成100克", False, "nutrition_record_draft"),
        ("把明天的训练改到后天", False, "schedule_change_draft"),
        ("帮我记录今天体重64公斤", False, "body_measurement_draft"),
        ("把每日热量目标改成2000千卡", False, "nutrition_target_draft"),
        ("把训练记录中的深蹲重量改成50公斤", False, None),
        ("把个人资料中的身高修改为175厘米", False, None),
        ("把食品库中的汉堡热量改成400千卡", False, None),
        ("删除食品库里的自定义酸奶", False, None),
        ("我今天没睡好", False, None),
        ("我今天不吃香菜", False, None),
        ("我朋友对花生过敏", False, None),
        ("如果我乳糖不耐受，怎么吃早餐", False, None),
        ("我不吃香菜", True, None),
        ("我对花生过敏", True, None),
        ("我只能在周末训练", True, None),
        ("我家只有一对哑铃", True, None),
        ("把酸奶加到食品库，我乳糖不耐受", True, "food_catalog_draft"),
    ]
    results = []
    for message, has_memory, expected_type in cases:
        plan = await router.route(message=message, images=[])
        results.append({"request": message, "plan": plan.model_dump(mode="json")})
        (ROOT / ".local" / "memory-routing-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        types = {task.task_type for task in plan.tasks}
        assert ("memory_write" in types) == has_memory, message
        if expected_type:
            assert expected_type in types, f"Inspect memory-routing-live.json: {message}"
        for task in plan.tasks:
            if task.task_type == "memory_write":
                assert task.memory_instructions
                assert all(item.evidence in message for item in task.memory_instructions)


@pytest.mark.asyncio(loop_scope="session")
async def test_food_catalog_and_autonomous_memory_real_api(live_account):
    client, user_id, _, _, _ = live_account
    conversation = await client.post("/agent/conversations", json={"title": "食品库与记忆验收"})
    conversation_id = conversation.json()["id"]
    results = []

    async def counts():
        async with SessionFactory() as session:
            return tuple(
                [
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            column == user_id,
                        )
                    )
                    for model, column in [
                        (Food, Food.owner_user_id),
                        (NutritionEntry, NutritionEntry.user_id),
                        (AgentMemory, AgentMemory.user_id),
                    ]
                ]
            )

    async def chat(message):
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        results.append({"request": message, "response": payload})
        (ROOT / ".local" / "food-catalog-memory-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert payload["status"] == "completed", "Inspect food-catalog-memory-live.json"
        return payload

    baseline = await counts()
    foods = await chat("帮我在食品库添加自定义食品麦当劳的双层吉士汉堡和一个香芋派")
    cards = foods["confirmation_cards"]
    assert len(cards) == 2 and all(card["operation_type"] == "food_create" for card in cards)
    assert await counts() == baseline
    for name in ("双层吉士", "香芋"):
        assert any(name in card["after"]["food"]["name"] for card in cards)
    card = cards[0]
    approval_key = str(uuid4())
    for _ in range(2):
        response = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": approval_key},
        )
        assert response.status_code == 200
    assert await counts() == (baseline[0] + 1, baseline[1], baseline[2])
    food_id = response.json()["result"]["resource_id"]
    stored = await client.get(f"/foods/{food_id}")
    assert stored.status_code == 200
    assert stored.json()["name"] == card["after"]["food"]["name"]
    await chat("我不吃香菜")
    assert await counts() == (baseline[0] + 1, baseline[1], baseline[2] + 1)
    await chat("我今天不吃葱，明天可以吃")
    assert await counts() == (baseline[0] + 1, baseline[1], baseline[2] + 1)
    mixed = await chat("把自制燕麦饼加入食品库，营养先按常见配方估算；我家只有一对哑铃")
    assert any(c["operation_type"] == "food_create" for c in mixed["confirmation_cards"])
    assert await counts() == (baseline[0] + 1, baseline[1], baseline[2] + 2)
    async with SessionFactory() as session:
        memories = (
            await session.scalars(
                select(AgentMemory).where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.deleted_at.is_(None),
                )
            )
        ).all()
        assert any("香菜" in m.content for m in memories)
        assert any("哑铃" in m.content for m in memories)
        assert not any(
            any(w in m.content for w in ("汉堡", "香芋", "燕麦饼", "食品库")) for m in memories
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_food_update_delete_real_api(live_account):
    client, user_id, _, _, _ = live_account
    async with SessionFactory() as session:
        nutrition = NutritionService(SqlAlchemyNutritionRepository(session))
        food, version = await nutrition.create_food(
            user_id,
            FoodCreateRequest(
                name="本轮验收燕麦饼",
                brand="自制",
                basis_amount_g=100,
                kcal=300,
                protein_g=10,
                carbs_g=40,
                fat_g=11,
            ),
            source="model_estimated",
            confidence="low",
        )
        meal = await nutrition.create_entry(
            user_id,
            NutritionEntryCreateRequest(
                meal_type="lunch",
                eaten_at=datetime.now(UTC),
                items=[NutritionItemInput(food_version_id=version.id, amount_g=200)],
            ),
        )
        food_id, meal_id = food.id, meal.id
        history = json.dumps({"items": meal.items, "totals": meal.totals}, sort_keys=True)
        await session.commit()
    conversation = await client.post("/agent/conversations", json={"title": "食品修改删除验收"})
    conversation_id = conversation.json()["id"]
    evidence = []

    async def chat(message):
        response = await client.post(
            "/agent/chat", json={"message": message, "conversation_id": conversation_id}
        )
        assert response.status_code == 200
        payload = response.json()
        evidence.append({"request": message, "response": payload})
        (ROOT / ".local" / "food-changes-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    updated = await chat(
        "把食品库里我自定义的本轮验收燕麦饼改名为本轮验收燕麦饼新版，"
        "每100克热量改为320千卡，其他字段和营养保持原样，先出草稿。"
    )
    assert updated["status"] == "completed", "Inspect food-changes-live.json"
    cards = updated["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "food_update"
    card = cards[0]
    assert float(card["after"]["food"]["kcal"]) == 320
    assert float(card["after"]["food"]["protein_g"]) == 10
    assert (await client.get(f"/foods/{food_id}")).json()["name"] == "本轮验收燕麦饼"
    key = str(uuid4())
    for _ in range(2):
        approved = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": key},
        )
        assert approved.status_code == 200
    latest = (await client.get(f"/foods/{food_id}")).json()
    assert latest["name"] == "本轮验收燕麦饼新版" and float(latest["kcal"]) == 320
    restored = await client.get(f"/agent/conversations/{conversation_id}/confirmations")
    assert restored.status_code == 200 and restored.json()["confirmation_cards"] == []
    deletion = await chat("从食品库删除我的本轮验收燕麦饼新版，只删除食品条目，历史午餐要保留。")
    assert deletion["status"] == "completed", "Inspect food-changes-live.json"
    cards = deletion["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "food_delete"
    card = cards[0]
    assert (await client.get(f"/foods/{food_id}")).status_code == 200
    approved = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={"expected_version": card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200
    assert (await client.get(f"/foods/{food_id}")).status_code == 404
    async with SessionFactory() as session:
        meal = await session.get(NutritionEntry, meal_id)
        assert json.dumps({"items": meal.items, "totals": meal.totals}, sort_keys=True) == history
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
            )
            == 0
        )
        assert (await session.get(Food, food_id)).deleted_at is not None
    # Two owned foods with the same name must cause a choice, never an arbitrary edit.
    async with SessionFactory() as session:
        nutrition = NutritionService(SqlAlchemyNutritionRepository(session))
        for brand in ["甲品牌", "乙品牌"]:
            await nutrition.create_food(
                user_id,
                FoodCreateRequest(
                    name="重复验收饼",
                    brand=brand,
                    basis_amount_g=100,
                    kcal=300,
                    protein_g=10,
                    carbs_g=40,
                    fat_g=11,
                ),
            )
        await session.commit()
    ambiguous = await chat("把食品库中的重复验收饼删除。")
    assert ambiguous["status"] == "needs_input" and not ambiguous["confirmation_cards"]


@pytest.mark.asyncio(loop_scope="session")
async def test_autonomous_memory_correction_and_retraction_real_api(live_account):
    client, user_id, _, _, _ = live_account
    response = await client.post("/agent/conversations", json={"title": "长期事实更正验收"})
    conversation_id = response.json()["id"]
    results = []
    for message in [
        "我家只有一对哑铃",
        "我家器械现在改成只有杠铃，没有哑铃了",
        "忘掉刚才我家只有杠铃的长期记忆，以后不要按这个器械限制训练",
    ]:
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        results.append({"request": message, "response": payload})
        (ROOT / ".local" / "memory-lifecycle-live.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert payload["status"] == "completed", "Inspect memory-lifecycle-live.json"
        async with SessionFactory() as session:
            active = (
                await session.scalars(
                    select(AgentMemory).where(
                        AgentMemory.user_id == user_id,
                        AgentMemory.deleted_at.is_(None),
                    )
                )
            ).all()
            if len(results) == 1:
                assert len(active) == 1 and "哑铃" in active[0].content
            elif len(results) == 2:
                assert len(active) == 1 and "杠铃" in active[0].content
            else:
                assert not active


@pytest.mark.asyncio(loop_scope="session")
async def test_profile_update_real_api(live_account):
    client, user_id, _, _, _ = live_account
    original = (await client.get("/profile")).json()
    plan = (await client.get("/training/plans/active")).json()
    targets = (await client.get("/nutrition/targets")).json()
    evidence = []

    async def chat(message):
        response = await client.post("/agent/chat", json={"message": message})
        assert response.status_code == 200
        payload = response.json()
        evidence.append({"request": message, "response": payload})
        (ROOT / ".local" / "profile-update-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert payload["status"] == "completed", "Inspect profile-update-live.json"
        return payload

    result = await chat(
        "把个人资料里的身高改成175厘米，每周训练天数改成4天，单次训练时长改为35分钟，"
        "其他资料保持原样；先给草稿，不修改已有计划、目标或长期记忆。"
    )
    cards = result["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "profile_update"
    card = cards[0]
    assert set(card["after"]["changes"]) == {
        "height_cm",
        "weekly_training_days",
        "session_duration_minutes",
    }
    assert (await client.get("/profile")).json() == original
    restored = await client.get(f"/agent/conversations/{result['conversation_id']}/confirmations")
    assert (
        restored.status_code == 200
        and restored.json()["confirmation_cards"][0]["confirmation_id"] == card["confirmation_id"]
    )
    key = str(uuid4())
    for _ in range(2):
        approved = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": key},
        )
        assert approved.status_code == 200
    updated = (await client.get("/profile")).json()
    assert Decimal(updated["height_cm"]) == 175
    assert updated["weekly_training_days"] == 4 and updated["session_duration_minutes"] == 35
    assert updated["version"] == original["version"] + 1
    for field in ("display_name", "sex", "birth_date", "experience_level", "weight_kg"):
        assert updated[field] == original[field]
    assert (await client.get("/training/plans/active")).json() == plan
    assert (await client.get("/nutrition/targets")).json() == targets
    weight_draft = await chat(
        "请把个人资料的最新体重更新为73.5公斤，先给确认草稿，保留旧体重记录，不改营养目标。"
    )
    weight_card = weight_draft["confirmation_cards"][0]
    assert weight_card["operation_type"] == "profile_update"
    assert set(weight_card["after"]["changes"]) == {"weight_kg"}
    approved = await client.post(
        f"/confirmations/{weight_card['confirmation_id']}/approve",
        json={"expected_version": weight_card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200
    assert Decimal((await client.get("/profile")).json()["weight_kg"]) == Decimal("73.5")
    async with SessionFactory() as session:
        weights = list(
            await session.scalars(
                select(BodyMeasurement.weight_kg).where(BodyMeasurement.user_id == user_id)
            )
        )
        assert Decimal("72") in weights and Decimal("73.5") in weights and len(weights) == 2
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
            )
            == 0
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_workout_set_changes_real_api(live_account):
    client, _, _, _, _ = live_account
    history = (await client.get("/workouts")).json()["list"]
    selected = history[0]
    workout_id = selected["id"]
    original = (await client.get(f"/workouts/{workout_id}")).json()
    summary = (await client.get(f"/workouts/{workout_id}/summary")).json()
    plan = (await client.get("/training/plans/active")).json()
    memories = (await client.get("/memories")).json()
    exercise = original["exercises"][0]
    target = next(s for s in exercise["sets"] if s["set_index"] == 2)
    evidence = []

    async def chat(message, conversation_id=None):
        response = await client.post(
            "/agent/chat", json={"message": message, "conversation_id": conversation_id}
        )
        assert response.status_code == 200
        payload = response.json()
        evidence.append({"request": message, "response": payload})
        (ROOT / ".local" / "workout-set-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert payload["status"] == "completed", "Inspect workout-set-live.json"
        return payload

    request = f"{selected['date']}那次训练中，{exercise['name_snapshot']}第2组"
    result = await chat(
        f"请把{request}的实际重量更正为40公斤、次数更正为8次，其他组和训练计划保持原样，先给草稿。"
    )
    assert len(result["confirmation_cards"]) == 1
    card = result["confirmation_cards"][0]
    assert card["operation_type"] == "workout_set_update"
    assert card["after"]["set_id"] == target["id"]
    assert set(card["after"]["changes"]) == {"weight_kg", "reps"}
    assert (await client.get(f"/workouts/{workout_id}")).json() == original
    restored = await client.get(f"/agent/conversations/{result['conversation_id']}/confirmations")
    assert restored.json()["confirmation_cards"][0]["confirmation_id"] == card["confirmation_id"]
    key = str(uuid4())
    for _ in range(2):
        approved = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": key},
        )
        assert approved.status_code == 200, approved.text
    corrected = (await client.get(f"/workouts/{workout_id}")).json()
    sets = corrected["exercises"][0]["sets"]
    current = next(s for s in sets if s["id"] == target["id"])
    assert Decimal(current["weight_kg"]) == 40 and current["reps"] == 8
    assert [s for s in sets if s["id"] != target["id"]] == [
        s for s in exercise["sets"] if s["id"] != target["id"]
    ]
    old_volume = Decimal(target["weight_kg"]) * target["reps"]
    corrected_summary = (await client.get(f"/workouts/{workout_id}/summary")).json()
    assert Decimal(corrected_summary["total_volume_kg"]) == (
        Decimal(summary["total_volume_kg"]) - old_volume + 320
    )
    result = await chat(
        f"把{request}作废，是误记，保留其他训练组和修订历史，先给草稿。",
        result["conversation_id"],
    )
    assert len(result["confirmation_cards"]) == 1
    card = result["confirmation_cards"][0]
    assert card["operation_type"] == "workout_set_void"
    assert card["after"]["set_id"] == target["id"]
    assert (await client.get(f"/workouts/{workout_id}")).json() == corrected
    approved = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={"expected_version": card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200, approved.text
    final = (await client.get(f"/workouts/{workout_id}")).json()
    assert all(s["id"] != target["id"] for s in final["exercises"][0]["sets"])
    final_summary = (await client.get(f"/workouts/{workout_id}/summary")).json()
    assert final_summary["completed_sets"] == summary["completed_sets"] - 1
    assert (
        Decimal(final_summary["total_volume_kg"])
        == Decimal(summary["total_volume_kg"]) - old_volume
    )
    revisions = (await client.get(f"/workouts/{workout_id}/revisions")).json()
    assert len(revisions) == 2
    assert (await client.get("/training/plans/active")).json() == plan
    assert (await client.get("/memories")).json() == memories


async def seed_saved_meal_acceptance(client):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    def food(name, amount, kcal, protein, carbs, fat):
        return {
            "name": name,
            "amount_g": amount,
            "basis_amount_g": 100,
            "kcal": kcal,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "source": "model_estimated",
            "confidence": "low",
        }

    bodies = [
        {
            "meal_type": "lunch",
            "eaten_at": f"{today}T12:00:00+08:00",
            "notes": "保留原备注",
            "items": [
                food("验收熟米饭", 200, 130, 3, 28, 1),
                food("验收鸡蛋", 100, 150, 13, 1, 10),
            ],
        },
        {
            "meal_type": "lunch",
            "eaten_at": f"{today}T13:00:00+08:00",
            "items": [food("验收面条", 100, 200, 5, 35, 3)],
        },
    ]
    entries = []
    for body in bodies:
        response = await client.post(
            "/nutrition/entries", json=body, headers={"Idempotency-Key": str(uuid4())}
        )
        assert response.status_code == 201, response.text
        saved = await client.get(f"/nutrition/entries/{response.json()['id']}")
        assert saved.status_code == 200, saved.text
        entries.append(saved.json())
    return today, entries


@pytest.mark.asyncio(loop_scope="session")
async def test_saved_meal_changes_real_api(live_account):
    client, user_id, _, _, _ = live_account
    day, entries = await seed_saved_meal_acceptance(client)
    original, other = entries
    original_entries = (await client.get("/nutrition/entries", params={"date": str(day)})).json()
    plan = (await client.get("/training/plans/active")).json()
    targets = (await client.get("/nutrition/targets")).json()
    initial = (await client.get("/nutrition/daily-summary", params={"date": str(day)})).json()
    evidence = []

    async def chat(message, conversation_id=None):
        response = await client.post(
            "/agent/chat", json={"message": message, "conversation_id": conversation_id}
        )
        assert response.status_code == 200
        payload = response.json()
        evidence.append({"request": message, "response": payload})
        (ROOT / ".local" / "saved-meal-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    result = await chat(
        f"请把{day}已经保存的午餐中验收熟米饭从200克更正为100克，鸡蛋和其他餐食不变，沿用原营养依据，先给草稿。"
    )
    assert result["status"] == "completed", "Inspect saved-meal-live.json"
    assert len(result["confirmation_cards"]) == 1
    card = result["confirmation_cards"][0]
    assert (
        card["operation_type"] == "nutrition_entry_update"
        and card["after"]["entry_id"] == original["id"]
    )
    assert card["after"]["changes"] == [{"item_index": 0, "amount_g": "100"}]
    assert (
        await client.get("/nutrition/entries", params={"date": str(day)})
    ).json() == original_entries
    restored = await client.get(f"/agent/conversations/{result['conversation_id']}/confirmations")
    assert restored.json()["confirmation_cards"][0]["confirmation_id"] == card["confirmation_id"]
    key = str(uuid4())
    for _ in range(2):
        approved = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": key},
        )
        assert approved.status_code == 200, approved.text
    updated = (await client.get(f"/nutrition/entries/{original['id']}")).json()
    assert (
        Decimal(updated["items"][0]["amount_g"]) == 100
        and updated["version"] == original["version"] + 1
    )
    assert updated["items"][1] == original["items"][1] and updated["notes"] == original["notes"]
    assert Decimal(updated["totals"]["kcal"]) == 280
    daily = (await client.get("/nutrition/daily-summary", params={"date": str(day)})).json()
    assert Decimal(daily["consumed"]["kcal"]) == Decimal(initial["consumed"]["kcal"]) - 130
    result = await chat(
        f"请删除{day}午餐中含验收熟米饭的那条已保存记录，这一餐是误记，其他餐食和食品库不变，先给草稿。",
        result["conversation_id"],
    )
    assert result["status"] == "completed" and len(result["confirmation_cards"]) == 1
    card = result["confirmation_cards"][0]
    assert (
        card["operation_type"] == "nutrition_entry_delete"
        and card["after"]["entry_id"] == original["id"]
    )
    assert (await client.get(f"/nutrition/entries/{original['id']}")).json() == updated
    approved = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={"expected_version": card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200, approved.text
    assert (await client.get(f"/nutrition/entries/{original['id']}")).status_code == 404
    assert (await client.get(f"/nutrition/entries/{other['id']}")).json() == other
    final = (await client.get("/nutrition/daily-summary", params={"date": str(day)})).json()
    assert Decimal(final["consumed"]["kcal"]) == Decimal(initial["consumed"]["kcal"]) - 410
    week = (
        await client.get(
            "/nutrition/weekly-summary",
            params={"start_date": str(day - timedelta(days=day.weekday()))},
        )
    ).json()
    assert Decimal(week["daily_average"]["kcal"]) == Decimal(final["consumed"]["kcal"])
    assert (await client.get("/training/plans/active")).json() == plan
    assert (await client.get("/nutrition/targets")).json() == targets
    from nxtrep_backend.db.models import NutritionEntryRevision

    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntryRevision)
                .where(NutritionEntryRevision.entry_id == UUID(original["id"]))
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(Food).where(Food.owner_user_id == user_id)
            )
            == 0
        )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("approved_first", [False, True])
async def test_meal_portion_followup_never_creates_duplicate_lunch(live_account, approved_first):
    client, _, _, _, _ = live_account
    day = str(datetime.now(ZoneInfo("Asia/Shanghai")).date())
    baseline = (await client.get("/nutrition/entries", params={"date": day})).json()
    evidence = []

    async def chat(message, conversation_id=None):
        if approved_first and conversation_id:
            events = []
            async with client.stream(
                "POST",
                f"/agent/conversations/{conversation_id}/messages",
                params={"granularity": "chunk"},
                json={"message": message},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
            assert events[-1]["event"] == "completed"
            result = events[-1]["response"]
        else:
            response = await client.post(
                "/agent/chat", json={"message": message, "conversation_id": conversation_id}
            )
            assert response.status_code == 200
            result = response.json()
        evidence.append({"request": message, "response": result})
        (ROOT / ".local" / f"meal-followup-{approved_first}-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert result["status"] == "completed", "Inspect meal-followup live evidence"
        assert len(result["confirmation_cards"]) == 1
        return result, result["confirmation_cards"][0]

    async def approve(card):
        response = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]["resource_id"]

    first, initial_card = await chat("今天午餐是泡椒鸡胗饭，米饭200克、鸡胗150克，先给草稿。")
    assert initial_card["operation_type"] == "nutrition_entry_create"
    if approved_first:
        entry_id = await approve(initial_card)
        original = (await client.get(f"/nutrition/entries/{entry_id}")).json()
    _, corrected_card = await chat("米饭约两百五十克", first["conversation_id"])
    entries = (await client.get("/nutrition/entries", params={"date": day})).json()
    if approved_first:
        assert corrected_card["operation_type"] == "nutrition_entry_update"
        assert corrected_card["after"]["entry_id"] == entry_id
        assert len(entries) == len(baseline) + 1
        assert (await client.get(f"/nutrition/entries/{entry_id}")).json() == original
    else:
        assert corrected_card["operation_type"] == "nutrition_entry_create"
        assert (
            corrected_card["after"]["replaces_confirmation_id"] == initial_card["confirmation_id"]
        )
        assert entries == baseline
    saved_id = await approve(corrected_card)
    final = (await client.get("/nutrition/entries", params={"date": day})).json()
    assert len(final) == len(baseline) + 1
    saved = next(e for e in final if e["id"] == saved_id)
    rice = next(f for f in saved["items"] if "米饭" in f["name"])
    assert Decimal(rice["amount_g"]) == 250
    if approved_first:
        assert saved_id == entry_id and saved["version"] == original["version"] + 1
        assert [f for f in saved["items"] if "米饭" not in f["name"]] == [
            f for f in original["items"] if "米饭" not in f["name"]
        ]
    _, dinner_card = await chat(
        "今天晚饭也吃了泡椒鸡胗饭，这是另外一餐，米饭200克、鸡胗150克，先给草稿。",
        first["conversation_id"],
    )
    assert dinner_card["operation_type"] == "nutrition_entry_create"
    assert dinner_card["after"]["entry"]["meal_type"] == "dinner"
    assert "replaces_confirmation_id" not in dinner_card["after"]
    assert (await client.get("/nutrition/entries", params={"date": day})).json() == final


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def live_account():
    account_id = uuid4()
    username, password = f"agent-accept-{uuid4().hex[:10]}", secrets.token_urlsafe(24)
    zone = ZoneInfo("Asia/Shanghai")
    today = datetime.now(zone).date()
    monday = today - timedelta(days=today.weekday())
    defines = ROOT / ".local" / f"agent-acceptance-{account_id}.json"
    try:
        async with SessionFactory() as session:
            user = User(id=account_id, username=username, password_setup_required=False)
            session.add(user)
            await session.flush()
            session.add_all(
                [
                    Credential(user_id=user.id, password_hash=hash_password(password)),
                    Profile(
                        user_id=user.id,
                        display_name="Agent验收",
                        sex="male",
                        birth_date=date(2004, 4, 2),
                        height_cm=Decimal("173"),
                        experience_level="beginner",
                        weekly_training_days=3,
                        session_duration_minutes=45,
                        timezone="Asia/Shanghai",
                    ),
                    UserGoal(user_id=user.id, goal_type="fat_loss_retain"),
                    UserConstraint(user_id=user.id, equipment=["哑铃"]),
                    BodyMeasurement(
                        user_id=user.id,
                        measured_at=datetime.now(UTC),
                        weight_kg=Decimal("72"),
                        body_fat_percent=Decimal("19"),
                        body_fat_method="smart_scale",
                        source="manual",
                    ),
                    NutritionEntry(
                        user_id=user.id,
                        meal_type="breakfast",
                        eaten_at=datetime.combine(today, time(8), zone),
                        items=[],
                        totals={"kcal": "500", "protein_g": "25", "carbs_g": "60", "fat_g": "15"},
                    ),
                ]
            )
            confirmations = SqlAlchemyConfirmationRepository(session)
            training = TrainingService(SqlAlchemyTrainingRepository(session), confirmations)
            draft = await training.create_from_template(
                user.id, UUID("20000000-0000-4000-8000-000000000001"), None
            )
            confirmation = await training.submit_draft(user.id, draft.id, draft.version)
            await DatabaseConfirmationService(confirmations).approve(
                user.id, confirmation.id, confirmation.version
            )
            events = list(
                (
                    await session.scalars(
                        select(CalendarEvent)
                        .where(CalendarEvent.user_id == user.id)
                        .order_by(CalendarEvent.scheduled_date)
                    )
                ).all()
            )
            workouts = WorkoutService(
                SqlAlchemyWorkoutRepository(session),
                SqlAlchemyTrainingRepository(session),
                confirmations,
            )
            for event, day in zip(events[:2], [monday - timedelta(days=2), monday], strict=True):
                started = datetime.combine(day, time(10), zone)
                aggregate = await workouts.create_workout(
                    user.id, WorkoutCreateRequest(calendar_event_id=event.id, started_at=started)
                )
                exercise = aggregate.exercises[0]
                for index in range(1, int(exercise.target_snapshot["sets"]) + 1):
                    await workouts.create_set(
                        user.id,
                        aggregate.workout.id,
                        WorkoutSetCreateRequest(
                            client_generated_id=uuid4(),
                            workout_exercise_id=exercise.id,
                            set_index=index,
                            weight_kg=Decimal("50"),
                            reps=10,
                            rir=3,
                            tags=["working"],
                            completed_at=started + timedelta(minutes=index),
                        ),
                    )
                await workouts.finish_workout(
                    user.id,
                    aggregate.workout.id,
                    WorkoutFinishRequest(
                        ended_at=started + timedelta(minutes=40),
                        expected_version=aggregate.workout.version,
                    ),
                )
            source_date = events[2].scheduled_date
            target_date = max(e.scheduled_date for e in events) + timedelta(days=2)
            await session.commit()
        async with httpx.AsyncClient(base_url=API, timeout=300) as client:
            login = await client.post(
                "/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200, "Local test-account login failed"
            client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
            if os.getenv("AGENT_DEVICE_SCENARIO") == "saved_meal_changes":
                await seed_saved_meal_acceptance(client)
            defines.parent.mkdir(exist_ok=True)
            defines.write_text(
                json.dumps(
                    {
                        "E2E_USERNAME": username,
                        "E2E_PASSWORD": password,
                        "E2E_DATE": today.isoformat(),
                        "E2E_SOURCE_DATE": source_date.isoformat(),
                        "E2E_TARGET_DATE": target_date.isoformat(),
                        "API_BASE_URL": "http://10.0.2.2:8000/api/v1",
                    }
                ),
                encoding="utf-8",
            )
            yield client, user.id, source_date, target_date, defines
    finally:
        defines.unlink(missing_ok=True)
        async with SessionFactory() as session:
            await session.execute(delete(User).where(User.id == account_id))
            await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_queries_and_proposals(live_account):
    client, user_id, source_date, target_date, _ = live_account
    evidence = []

    async def chat(message):
        response = await client.post("/agent/chat", json={"message": message})
        assert response.status_code == 200, f"Agent API failed with HTTP {response.status_code}"
        payload = response.json()
        evidence.append({"request": message, "response": payload})
        (ROOT / ".local" / "agent-live-acceptance.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert payload["status"] == "completed", "Inspect redacted local acceptance evidence"
        assert "回答：" not in payload["message"] and "分析：" not in payload["message"]
        return payload

    query = await chat("我上周和本周分别训练了几次？今天记录的热量和蛋白质是多少？请查实际记录。")
    names = {r["tool_name"] for b in query["analysis_results"] for r in b.get("tool_runs", [])}
    assert "read_recent_workouts" in names
    week_records = [
        r
        for b in query["analysis_results"]
        for r in (b.get("result") or {}).get("queried_records", [])
        if r["tool_name"] == "read_recent_workouts"
    ]
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    monday = today - timedelta(days=today.weekday())
    assert {r["period"]["start_date"] for r in week_records} >= {
        monday.isoformat(),
        (monday - timedelta(days=7)).isoformat(),
    }
    assert all(r["summary"]["workout_count"] == 1 for r in week_records)
    assert names.intersection({"read_nutrition_entries", "read_daily_nutrition_summary"})
    assert "500" in query["message"] and "25" in query["message"]

    meal = await chat(
        "帮我记今天午餐：两个水煮鸡蛋和一碗熟米饭。先按常见份量估算，给我待确认草稿。"
    )
    card = next(
        c for c in meal["confirmation_cards"] if c["operation_type"] == "nutrition_entry_create"
    )
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == 1
        )
    rejection = await client.post(
        f"/confirmations/{card['confirmation_id']}/reject",
        json={"expected_version": card["version"], "reason": "验收撤销草稿"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert rejection.status_code == 200

    schedule = await chat(
        f"把{source_date}的训练移到{target_date}，使用顺延方式，先生成调整草稿等我确认。"
    )
    assert any(c["operation_type"] == "calendar_reschedule" for c in schedule["confirmation_cards"])
    progression = await chat(
        "根据我最近一次已经完成的训练记录，生成下次的保守重量递增草稿，等我确认再生效。"
    )
    assert any(
        c["operation_type"] == "training_progression_apply"
        for c in progression["confirmation_cards"]
    )
    trace = await client.get("/agent/tool-runs")
    assert trace.status_code == 200 and trace.json()["list"]
    assert all("arguments" not in item and "token" not in item for item in trace.json()["list"])


@pytest.mark.asyncio(loop_scope="session")
async def test_local_stream_keeps_connection_until_terminal_event(live_account):
    client, _, _, _, _ = live_account
    events = []
    conversation = await client.post("/agent/conversations", json={"title": None})
    assert conversation.status_code == 201
    async with client.stream(
        "POST",
        f"/agent/conversations/{conversation.json()['id']}/messages",
        json={
            "message": "请查我今天实际记录的热量和蛋白质，别用计划目标代替。",
        },
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events and events[-1]["event"] == "completed"
    assert events[-1]["response"]["status"] == "completed"
    assert "500" in events[-1]["response"]["message"]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(os.getenv("RUN_AGENT_DEVICE_TESTS") != "1", reason="Android acceptance opt-in")
async def test_android_chat_confirmation_flow(live_account):
    _, _, _, _, defines = live_account
    sdk = Path(os.getenv("FLUTTER_ROOT", "D:/develop/flutter"))
    food_changes = os.getenv("AGENT_DEVICE_SCENARIO") == "food_changes"
    profile_changes = os.getenv("AGENT_DEVICE_SCENARIO") == "profile_changes"
    workout_changes = os.getenv("AGENT_DEVICE_SCENARIO") == "workout_changes"
    saved_meal_changes = os.getenv("AGENT_DEVICE_SCENARIO") == "saved_meal_changes"
    food_memory = os.getenv("AGENT_DEVICE_SCENARIO") in {"food_memory", "food_changes"}
    integration_file = (
        "local_food_memory_smoke_test.dart"
        if food_memory
        else "local_agent_capabilities_smoke_test.dart"
    )
    if profile_changes:
        integration_file = "local_profile_smoke_test.dart"
    if workout_changes:
        integration_file = "local_workout_set_smoke_test.dart"
    if saved_meal_changes:
        integration_file = "local_saved_meal_smoke_test.dart"
    command = [
        str(sdk / "bin/cache/dart-sdk/bin/dart.exe"),
        str(sdk / "bin/cache/flutter_tools.snapshot"),
        "test",
        "--no-pub",
        f"integration_test/{integration_file}",
        "-d",
        "emulator-5554",
        f"--dart-define-from-file={defines}",
    ]
    if meal_message := os.getenv("AGENT_DEVICE_MEAL_MESSAGE"):
        command.append(f"--dart-define=E2E_MEAL_MESSAGE={meal_message}")
    if food_changes:
        command.append("--dart-define=E2E_FOOD_CHANGES=true")
    environment = dict(os.environ)
    environment["JAVA_TOOL_OPTIONS"] = "-Djdk.net.unixdomain.tmpdir=C:\\Windows\\Temp"
    log = (
        ROOT
        / ".local"
        / ("food-memory-android-acceptance.log" if food_memory else "agent-android-acceptance.log")
    )
    if profile_changes:
        log = ROOT / ".local" / "profile-android-acceptance.log"
    if workout_changes:
        log = ROOT / ".local" / "workout-set-android-acceptance.log"
    if saved_meal_changes:
        log = ROOT / ".local" / "saved-meal-android-acceptance.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            command,
            cwd=ROOT / "frontend",
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    assert result.returncode == 0, "Android acceptance failed; inspect local log (no credentials)"


@pytest.mark.asyncio(loop_scope="session")
async def test_brand_meal_draft_and_confirmed_save(live_account):
    client, user_id, _, _, _ = live_account
    async with SessionFactory() as session:
        before = await session.scalar(
            select(func.count())
            .select_from(NutritionEntry)
            .where(NutritionEntry.user_id == user_id)
        )
    response = await client.post(
        "/agent/chat", json={"message": "我今天的午餐是麦当劳的两个双层吉士汉堡"}
    )
    assert response.status_code == 200
    payload = response.json()
    (ROOT / ".local" / "agent-brand-meal-acceptance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert payload["status"] == "completed", "Inspect brand-meal acceptance evidence"
    card = next(
        c for c in payload["confirmation_cards"] if c["operation_type"] == "nutrition_entry_create"
    )
    assert card["after"]["entry"]["meal_type"] == "lunch"
    assert any("汉堡" in item["name"] for item in card["after"]["preview"]["items"])
    assert Decimal("500") < Decimal(card["after"]["preview"]["totals"]["kcal"]) < Decimal("1200"), (
        "Two portions must not be multiplied twice"
    )
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == before
        )
    approval = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={"expected_version": card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approval.status_code == 200
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == before + 1
        )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("topic", ["训练", "饮食", "恢复"])
async def test_public_web_knowledge_uses_actual_search_and_sources(live_account, topic):
    client, _, _, _, _ = live_account
    response = await client.post(
        "/agent/chat",
        json={
            "message": (
                f"请联网查{topic}相关的通用健康知识，优先权威来源，"
                "给我两条实用建议及来源链接。不要查我的个人记录。"
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    (ROOT / ".local" / f"agent-web-{topic}-acceptance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert payload["status"] == "completed", "Inspect web acceptance evidence"
    assert any(
        run["tool_name"] == "search_web"
        for branch in payload["analysis_results"]
        for run in branch.get("tool_runs", [])
    )
    assert any(
        c["source_type"] == "web" and c["source_id"].startswith("https://")
        for c in payload["citations"]
    )
    assert "http" in payload["message"]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "question,streaming",
    [
        ("肌酸对力量训练有哪些作用，通常怎么补充？", False),
        ("成年人每天摄入的膳食纤维一般建议是多少？", False),
        ("力量训练后泡冷水对肌肉增长有什么影响？", True),
    ],
)
async def test_missing_local_evidence_searches_web_without_explicit_request(
    live_account,
    question,
    streaming,
):
    client, _, _, _, _ = live_account
    endpoint = "/agent/chat/stream" if streaming else "/agent/chat"
    response = await client.post(endpoint, json={"message": question})
    assert response.status_code == 200
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        completed = [event for event in events if event["event"] == "completed"]
        assert completed, "Stream did not complete"
        payload = completed[-1]["response"]
        assert (
            "".join(
                event.get("delta") or "" for event in events if event["event"] == "message_delta"
            )
            == payload["message"]
        )
    else:
        payload = response.json()
    evidence_file = ROOT / ".local" / f"agent-auto-web-{uuid4().hex[:8]}.json"
    evidence_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    assert payload["status"] == "completed", "Inspect automatic web acceptance evidence"
    assert any(
        run["tool_name"] == "search_web"
        for branch in payload["analysis_results"]
        for run in branch.get("tool_runs", [])
    )
    assert any(c["source_type"] == "web" for c in payload["citations"])
    local = next(
        branch["result"]["local_knowledge"]
        for branch in payload["analysis_results"]
        if branch.get("result", {}).get("local_knowledge")
    )
    assert local["web_search_required"] is True
    assert local["coverage"]["sufficient"] is False
    assert any(
        c["source_id"] in payload["message"]
        for c in payload["citations"]
        if c["source_type"] == "web"
    )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("partial", [True, False])
async def test_real_model_distinguishes_partial_from_complete_local_evidence(partial):
    service = MagicMock()
    content = (
        "成年人的建议蛋白质摄入量为每天每公斤体重 1.2 至 1.6 克。"
        if not partial
        else "蛋白质是人体的重要营养素。"
    )
    service.retrieve = AsyncMock(
        return_value=(
            KnowledgeRetrievalHit(
                chunk_id=uuid4(),
                document_id=uuid4(),
                source_id=uuid4(),
                source_key="synthetic-coverage-test",
                source_title="仅用于覆盖判断的测试片段",
                source_uri=None,
                source_version=1,
                topic="nutrition",
                locale="zh-CN",
                content=content,
                section_path=None,
                page_numbers=(),
                score=0.99,
                match_type="hybrid",
            ),
        )
    )
    web_handler = MagicMock()
    # The real network path is covered above; this test isolates the actual
    # model's sufficiency judgment using synthetic evidence, not published advice.
    web_handler.execute = AsyncMock(return_value=None)
    handler = KnowledgeRetrievalBranchHandler(
        service,
        candidate_k=20,
        top_k=5,
        coverage_model=build_text_model(get_settings()),
    )
    if partial:
        handler._web_handler = web_handler
    branch = AgentBranchInput(
        user_id=uuid4(),
        message="成年人的建议蛋白质摄入量每天每公斤体重是多少？",
        task=AgentIntentTask(
            task_type="knowledge_retrieval",
            confidence="high",
            routing_reason="test local evidence coverage",
        ),
        images=(),
    )
    if partial:
        web_handler.execute.return_value = AgentBranchResult(
            task_type="knowledge_retrieval",
            status="completed",
            result={"answer": "测试结果"},
        )
    result = await handler.execute(branch)
    assert result.result["local_knowledge"]["coverage"]["sufficient"] is (not partial)
    if partial:
        assert result.result["local_knowledge"]["evidence_status"] == "available"
        web_handler.execute.assert_awaited_once()
