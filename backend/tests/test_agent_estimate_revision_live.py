"""Opt-in real-model revision checks; only disposable synthetic account data leaves localhost."""

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentConversation, NutritionEntry
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState
from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest
from nxtrep_backend.schemas.nutrition import (
    CustomFoodDraftRequest,
    FoodCreateRequest,
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionTargetDraftRequest,
)
from nxtrep_backend.schemas.profile import ProfileUpdateRequest
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.profile import ProfileService
from nxtrep_backend.services.training import TrainingService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1"
    or os.getenv("RUN_ESTIMATE_REVISION_LIVE_TESTS") != "1",
    reason="Opt-in configured model + local API, synthetic accounts only",
)


async def seed_context(session, user_id, conversation_id, card, task_type, text):
    conversation = await session.get(AgentConversation, UUID(conversation_id))
    conversation.task_state = AgentTaskState(
        active_task=AgentTask(
            task_type=task_type,
            status="awaiting_confirmation",
            entities={"confirmation_id": str(card.id)},
        )
    ).model_dump(mode="json")
    repository = SqlAlchemyConversationRepository(session)
    await repository.append_message(
        conversation=conversation, role="user", content="这是用于验收的虚构数据，请生成待确认草稿。"
    )
    await repository.append_message(conversation=conversation, role="assistant", content=text)
    await session.commit()


class LiveChat:
    def __init__(self, client, conversation_id, scenario):
        self.client, self.conversation_id = client, conversation_id
        self.evidence, self.path = [], ROOT / ".local" / f"revision-live-{scenario}-20261011.json"

    async def send(self, message):
        async with SessionFactory() as session:
            conversation = await session.get(AgentConversation, UUID(self.conversation_id))
            state_before = conversation.task_state
        response = await self.client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": self.conversation_id,
                "client_turn_id": str(uuid4()),
                "context_hints": {
                    "timezone": "Asia/Shanghai",
                    "occurred_at": datetime.now(UTC).isoformat(),
                },
            },
        )
        data = response.json()
        self.evidence.append(
            {
                "message": message,
                "task_state_before": state_before,
                "http_status": response.status_code,
                "response": data,
            }
        )
        self.path.write_text(
            json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert response.status_code == 200, "Inspect synthetic local acceptance evidence"
        assert data["status"] == "completed", "Inspect synthetic local acceptance evidence"
        return data


@pytest.mark.asyncio(loop_scope="session")
async def test_pending_to_saved_estimate_correction_then_portion_patch_is_one_meal(live_account):  # noqa: F811
    client, user_id, _, _, _ = live_account
    conversation_id = (await client.post("/agent/conversations", json={})).json()["id"]
    async with SessionFactory() as session:
        repo = SqlAlchemyConfirmationRepository(session)
        service = NutritionService(SqlAlchemyNutritionRepository(session), repo)
        _, rice = await service.create_food(
            user_id,
            FoodCreateRequest(
                name="虚构验收熟米饭",
                basis_amount_g=100,
                kcal=130,
                protein_g=3,
                carbs_g=28,
                fat_g=0.5,
            ),
        )
        body = NutritionEntryCreateRequest(
            meal_type="lunch",
            eaten_at=datetime.now(UTC),
            notes="虚构验收，初稿暂按较多用油、老豆腐估算。",
            items=[
                NutritionItemInput(
                    name="虚构验收鸡肉菜",
                    amount_g=200,
                    basis_amount_g=200,
                    kcal=360,
                    protein_g=36,
                    carbs_g=6,
                    fat_g=22,
                    source="model_estimated",
                    confidence="low",
                ),
                NutritionItemInput(
                    name="虚构验收豆腐菜",
                    amount_g=200,
                    basis_amount_g=200,
                    kcal=300,
                    protein_g=20,
                    carbs_g=10,
                    fat_g=20,
                    source="model_estimated",
                    confidence="low",
                ),
                NutritionItemInput(food_version_id=rice.id, amount_g=200),
            ],
        )
        old = await service.propose_entry(user_id=user_id, body=body)
        old_id = str(old.id)
        old_preview = old.after["preview"]
        before_count = await session.scalar(
            select(func.count())
            .select_from(NutritionEntry)
            .where(NutritionEntry.user_id == user_id)
        )
        await seed_context(
            session,
            user_id,
            conversation_id,
            old,
            "nutrition_record_draft",
            "已生成午餐饮食草稿：鸡肉菜200克、豆腐菜200克、米饭200克。脂肪暂估43克，尚待确认。",
        )
    chat = LiveChat(client, conversation_id, "meal")
    query = await chat.send("这份午餐草稿目前脂肪估算多少？先不要改。")
    assert not query["confirmation_cards"]
    revised = await chat.send(
        "脂肪偏高了，实际是去皮水煮鸡肉和清蒸豆腐，不太油。所有食物份量保持不变，请重估。"
    )
    assert len(revised["confirmation_cards"]) == 1
    pending = revised["confirmation_cards"][0]
    assert pending["operation_type"] == "nutrition_entry_create"
    assert pending["after"]["replaces_confirmation_id"] == old_id
    preview = pending["after"]["preview"]
    assert [Decimal(item["amount_g"]) for item in preview["items"]] == [200, 200, 200]
    for key, value in old_preview["items"][2].items():
        if key in {
            "amount_g",
            "basis_amount_g",
            "kcal",
            "protein_g",
            "carbs_g",
            "fat_g",
        } or key.startswith("total_"):
            assert Decimal(preview["items"][2][key]) == Decimal(value)
        else:
            assert preview["items"][2][key] == value
    assert Decimal(preview["totals"]["fat_g"]) < 43
    assert all(item.get("estimate_assumptions") for item in pending["after"]["entry"]["items"][:2])
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == before_count
        )
    approved = await client.post(
        f"/confirmations/{pending['confirmation_id']}/approve",
        json={"expected_version": pending["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200
    entry_id = approved.json()["result"]["resource_id"]
    original = (await client.get(f"/nutrition/entries/{entry_id}")).json()
    reestimated = await chat.send(
        "豆腐的蛋白质估高了，实际是带汤嫩豆腐，不是老豆腐，请重估豆腐的营养。鸡肉、米饭和所有份量保持不变。"
    )
    assert len(reestimated["confirmation_cards"]) == 1
    saved_card = reestimated["confirmation_cards"][0]
    assert saved_card["operation_type"] == "nutrition_entry_update"
    assert saved_card["after"]["entry_id"] == entry_id
    assert any(change.get("nutrition_estimate") for change in saved_card["after"]["changes"])
    assert (await client.get(f"/nutrition/entries/{entry_id}")).json() == original
    final = await chat.send("米饭改成150克，其他不变")
    final_card = final["confirmation_cards"][0]
    assert final_card["after"]["entry_id"] == entry_id
    assert final_card["after"]["replaces_confirmation_id"] == saved_card["confirmation_id"]
    assert any(change.get("nutrition_estimate") for change in final_card["after"]["changes"])
    portion = await chat.send("豆腐也改成150克，其他不变，先不要确认")
    portion_card = portion["confirmation_cards"][0]
    assert portion_card["after"]["replaces_confirmation_id"] == final_card["confirmation_id"]
    after_portion = await chat.send(
        "豆腐的蛋白质还是估高了，实际大半都是汤。所有份量按上一张草稿保持不变，请重新估算豆腐的营养。"
    )
    final_card = after_portion["confirmation_cards"][0]
    assert final_card["after"]["entry_id"] == entry_id
    assert final_card["after"]["replaces_confirmation_id"] == portion_card["confirmation_id"]
    tofu_change = next(
        change for change in final_card["after"]["changes"] if change["item_index"] == 1
    )
    assert Decimal(tofu_change["amount_g"]) == 150
    assert tofu_change["nutrition_estimate"]["assumptions"].strip()
    assert (await client.get(f"/nutrition/entries/{entry_id}")).json() == original
    approval_key = str(uuid4())
    for _ in range(2):
        response = await client.post(
            f"/confirmations/{final_card['confirmation_id']}/approve",
            json={"expected_version": final_card["version"]},
            headers={"Idempotency-Key": approval_key},
        )
        assert response.status_code == 200
    entry = (await client.get(f"/nutrition/entries/{entry_id}")).json()
    assert entry["id"] == original["id"] and entry["version"] == original["version"] + 1
    assert [Decimal(item["amount_g"]) for item in entry["items"]] == [200, 150, 150]
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )
            == before_count + 1
        )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("kind", ["profile", "food", "body", "target", "plan"])
async def test_other_pending_business_drafts_use_real_revision_tool(live_account, kind):  # noqa: F811
    client, user_id, _, _, _ = live_account
    conversation_id = (await client.post("/agent/conversations", json={})).json()["id"]
    async with SessionFactory() as session:
        repo = SqlAlchemyConfirmationRepository(session)
        nutrition = NutritionService(SqlAlchemyNutritionRepository(session), repo)
        if kind == "profile":
            service = ProfileService(
                SqlAlchemyProfileRepository(session), SqlAlchemyBodyRepository(session), repo
            )
            snapshot = await service.read_update_snapshot(user_id)
            old = await service.propose_update(
                user_id,
                ProfileUpdateRequest(
                    expected_version=snapshot["version"], height_cm=175, weekly_training_days=4
                ),
            )
            task_type, text, message = (
                "profile_update_draft",
                "资料草稿待确认：身高175厘米、每周4天。",
                "不对，身高改成176厘米，每周4天不变，只修订刚才的待确认资料草稿。",
            )
        elif kind == "food":
            old = await nutrition.propose_custom_food(
                user_id=user_id,
                body=CustomFoodDraftRequest(
                    name="虚构验收食品",
                    basis_amount_g=100,
                    kcal=200,
                    protein_g=10,
                    carbs_g=20,
                    fat_g=8,
                    notes="虚构配方暂估",
                ),
            )
            task_type, text, message = (
                "food_catalog_draft",
                "已创建虚构验收食品的待确认食品库草稿，每100克200千卡、蛋白质10克、碳水20克、脂肪8克。",
                "刚才的自定义食品草稿脂肪改为6克、热量182千卡，其余不变，按我补充的数值更正，先别保存到食品库。",
            )
        elif kind == "body":
            service = BodyService(SqlAlchemyBodyRepository(session), repo)
            old = await service.propose_measurement(
                user_id=user_id,
                body=BodyMeasurementCreateRequest(
                    measured_at=datetime.now(UTC), weight_kg=70, waist_cm=80, source="user_provided"
                ),
            )
            task_type, text, message = (
                "body_measurement_draft",
                "身体测量草稿待确认：体重70公斤，腰围80厘米。",
                "不对，体重是69公斤，腰围80厘米不变，修订刚才的测量草稿。",
            )
        elif kind == "target":
            draft = await nutrition.create_target_draft(
                user_id,
                NutritionTargetDraftRequest(
                    effective_from=date.today(),
                    kcal_min=1800,
                    kcal_max=2000,
                    protein_min_g=100,
                    protein_max_g=130,
                    carbs_min_g=200,
                    carbs_max_g=240,
                    fat_min_g=50,
                    fat_max_g=65,
                ),
            )
            old = await nutrition.submit_target(user_id, draft.id, draft.version)
            task_type, text, message = (
                "nutrition_target_draft",
                "每日营养目标草稿待确认：脂肪50到65克。",
                "刚才营养目标草稿的脂肪上限改为60克，其余不变，先别生效。",
            )
        else:
            service = TrainingService(SqlAlchemyTrainingRepository(session), repo)
            draft = await service.create_suggested_draft(
                user_id=user_id,
                source="test",
                template_id=UUID("20000000-0000-4000-8000-000000000001"),
            )
            old = await service.submit_draft(user_id, draft.id, draft.version)
            task_type, text, message = (
                "training_plan_draft",
                "训练计划草稿已生成，待确认后启用。",
                "刚才的训练计划草稿只把名字改成虚构验收修订计划，动作安排保持原样，先别启用。",
            )
        old_id = str(old.id)
        await seed_context(session, user_id, conversation_id, old, task_type, text)
    response = await LiveChat(client, conversation_id, kind).send(message)
    assert len(response["confirmation_cards"]) == 1
    card = response["confirmation_cards"][0]
    assert card["after"]["replaces_confirmation_id"] == old_id
    assert card["operation_type"] == old.operation_type
    assert any(
        run["tool_name"] == "propose_pending_draft_revision"
        for branch in response["analysis_results"]
        for run in branch.get("tool_runs", [])
    )
    original = (await client.get(f"/confirmations/{old_id}")).json()
    assert original["status"] == "rejected"
