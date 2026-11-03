from dataclasses import replace
from datetime import date

from langgraph.types import StreamWriter

from nxtrep_backend.agents.state import AgentGraphState
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.agents.today_training_answer import direct_today_training_answer
from nxtrep_backend.schemas.agent import AgentExecutionBundle
from nxtrep_backend.services.agent_execution import (
    AgentBranchExecutor,
)
from nxtrep_backend.services.agent_planning import (
    AgentRequestPlanner,
)
from nxtrep_backend.services.agent_safety import AgentExecutionSafetyValidator
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext


def _discard_stream_event(_event: object) -> None:
    pass


class AgentGraphStateError(RuntimeError):
    pass


class AgentGraphNodes:
    def __init__(
        self,
        *,
        planner: AgentRequestPlanner,
        executor: AgentBranchExecutor,
        synthesizer: AgentResponseSynthesizer,
        safety_validator: AgentExecutionSafetyValidator | None = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._synthesizer = synthesizer
        self._safety_validator = safety_validator or AgentExecutionSafetyValidator()

    async def plan_request(
        self,
        state: AgentGraphState,
    ) -> dict:
        user_id = state.get("user_id")
        request = state.get("request")
        conversation_context = state.get("conversation_context", AgentConversationContext())

        if user_id is None or request is None:
            raise AgentGraphStateError("Planning requires user_id and request")

        planned_request = await self._planner.plan(
            user_id=user_id,
            request=request,
            conversation_context=conversation_context,
        )

        return {
            "planned_request": planned_request,
            "conversation_context": planned_request.conversation_context,
        }

    async def execute_branches(
        self,
        state: AgentGraphState,
    ) -> dict:
        user_id = state.get("user_id")
        request = state.get("request")
        planned_request = state.get("planned_request")

        if user_id is None or request is None or planned_request is None:
            raise AgentGraphStateError(
                "Branch execution requires user_id, request and planned_request"
            )

        execution_bundle = await self._executor.execute(
            user_id=user_id,
            message=request.message,
            planned_request=planned_request,
        )

        return {
            "execution_bundle": execution_bundle,
        }

    async def validate_execution(
        self,
        state: AgentGraphState,
    ) -> dict:
        execution_bundle = state.get("execution_bundle")
        if execution_bundle is None:
            raise AgentGraphStateError("Safety validation requires execution_bundle")
        bundle = self._safety_validator.validate(execution_bundle)
        context = state.get("conversation_context", AgentConversationContext())
        task_state = TaskStateManager.load(context.task_state)
        for branch in bundle.branch_results:
            if task_state.active_task and branch.task_type == task_state.active_task.task_type:
                payloads = list(branch.operation_results)
                if branch.result:
                    payloads.extend(branch.result.get("task_tool_results", []))
                    if isinstance(branch.result.get("review"), dict):
                        payloads.append(branch.result["review"])
                task_state = TaskStateManager.commit_results(
                    task_state,
                    payloads,
                    branch.confirmation_cards,
                    last_tool_call=branch.tool_runs[-1] if branch.tool_runs else None,
                )
                if branch.status == "needs_input":
                    task_state.active_task.missing_fields = branch.missing_fields
                    task_state.active_task.status = "collecting"
                elif branch.status == "failed":
                    task_state.active_task.status = "failed"
        return {
            "execution_bundle": bundle,
            "conversation_context": replace(context, task_state=task_state.model_dump(mode="json")),
        }

    async def synthesize_response(
        self,
        state: AgentGraphState,
        writer: StreamWriter = _discard_stream_event,
    ) -> dict:
        request = state.get("request")
        execution_bundle = state.get("execution_bundle")
        conversation_context = state.get("conversation_context", AgentConversationContext())

        if request is None or execution_bundle is None:
            raise AgentGraphStateError("Response synthesis requires request and execution_bundle")

        direct_answer = self._direct_task_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_failure_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_training_plan_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = direct_today_training_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_knowledge_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_read_only_answer(execution_bundle)
        if direct_answer is not None:
            direct_answer += AgentResponseSynthesizer._web_source_suffix(
                direct_answer, execution_bundle
            )
            if state.get("streaming", False):
                writer(
                    {
                        "event": "message_delta",
                        "node": "synthesize_response",
                        "delta": direct_answer,
                    }
                )
            return {"response_message": direct_answer}

        synthesis_options = {
            "user_message": request.message,
            "execution_bundle": execution_bundle,
            "conversation_context": conversation_context,
        }
        if state.get("streaming", False):
            response_parts: list[str] = []
            async for delta in self._synthesizer.astream(
                **synthesis_options,
                allow_fallback=False,
            ):
                response_parts.append(delta)
                writer(
                    {
                        "event": "message_delta",
                        "node": "synthesize_response",
                        "delta": delta,
                    }
                )
            response_message = "".join(response_parts)
        else:
            response_message = await self._synthesizer.synthesize(**synthesis_options)

        return {
            "response_message": response_message,
        }

    @staticmethod
    def _direct_training_plan_answer(
        execution_bundle: AgentExecutionBundle,
    ) -> str | None:
        if len(execution_bundle.branch_results) != 1:
            return None
        branch = execution_bundle.branch_results[0]
        if (
            branch.task_type != "training_plan_draft"
            or branch.status != "completed"
            or not any(
                card.operation_type == "training_plan_activate"
                for card in branch.confirmation_cards
            )
        ):
            return None
        draft = next(
            (
                operation.get("draft")
                for operation in branch.operation_results
                if operation.get("status") == "confirmation_required"
                and isinstance(operation.get("draft"), dict)
            ),
            None,
        )
        if draft is None:
            return None
        name = " ".join(str(draft.get("name") or "训练计划").split())[:80]
        frequency = draft.get("weekly_frequency")
        days = draft.get("days")
        frequency_text = (
            f"按每周 {frequency} 次安排" if type(frequency) is int else "的训练安排如下"
        )
        day_count = len(days) if isinstance(days, list) else 0
        durations = (
            [
                day["estimated_minutes"]
                for day in days
                if isinstance(day, dict) and type(day.get("estimated_minutes")) is int
            ]
            if isinstance(days, list)
            else []
        )
        context = branch.result.get("personal_context") if isinstance(branch.result, dict) else None
        analysis = AgentGraphNodes._training_plan_analysis(
            context if isinstance(context, dict) else {},
            frequency=frequency if type(frequency) is int else None,
            day_count=day_count,
            duration_range=(min(durations), max(durations)) if durations else None,
        )
        return (
            f"「{name}」{frequency_text}。\n\n"
            f"{analysis}"
        )

    @staticmethod
    def _training_plan_analysis(
        context: dict,
        *,
        frequency: int | None,
        day_count: int,
        duration_range: tuple[int, int] | None = None,
    ) -> str:
        duration_text = ""
        if duration_range is not None:
            shortest, longest = duration_range
            duration_text = (
                f"，每次约 {shortest} 分钟"
                if shortest == longest
                else f"，每次约 {shortest}–{longest} 分钟"
            )
        parts = [f"包含 {day_count} 个训练日{duration_text}。"]
        profile = context.get("profile")
        profile = profile if isinstance(profile, dict) else {}
        goal_labels = {
            "muscle_gain": "增肌塑形",
            "fat_loss_retain": "减脂保肌",
            "strength": "提升力量",
        }
        goal = goal_labels.get(context.get("goal_type"))
        available_days = profile.get("weekly_training_days")
        goal_reasons = {
            "muscle_gain": "需要持续训练，并根据完成情况逐步增加刺激",
            "fat_loss_retain": "规律力量训练有助于保留肌肉，还需配合饮食管理",
            "strength": "应重视动作质量，并循序调整负重",
        }
        if goal:
            parts.append(f"你的目标是{goal}：{goal_reasons[context['goal_type']]}。")
        if type(available_days) is int and frequency is not None:
            if available_days == frequency:
                parts.append(f"每周 {frequency} 次与你填写的可训练天数一致。")
            else:
                parts.append(
                    f"你填写的每周可训练 {available_days} 天，"
                    f"这份计划安排 {frequency} 天，可以按实际空闲时间调整。"
                )
        preferred_minutes = profile.get("session_duration_minutes")
        if type(preferred_minutes) is int and duration_range is not None:
            _, longest = duration_range
            if longest <= preferred_minutes:
                parts.append(f"单次时长在你可用的 {preferred_minutes} 分钟内。")
            else:
                parts.append(
                    f"你填写的单次可训练约 {preferred_minutes} 分钟，"
                    "这份计划可能超时，可以适当减少动作或组数。"
                )

        measurements = context.get("measurements")
        measurements = measurements if isinstance(measurements, dict) else {}
        metrics = []
        height = profile.get("height_cm")
        if height is not None:
            metrics.append(f"身高 {height} cm")
        weight = measurements.get("weight_kg")
        if weight is not None:
            metrics.append(f"体重 {weight} kg")
        body_fat = measurements.get("body_fat_percent")
        if body_fat is not None:
            metrics.append(f"体脂 {body_fat}%")
        if metrics:
            parts.append(
                f"已读取{'、'.join(metrics)}；"
                "这些指标可作后续观察基线，不能单凭它们判断动作或负重是否合适。"
            )
            if any(
                AgentGraphNodes._is_old_record(measurements.get(field))
                for field in ("weight_recorded_at", "body_fat_recorded_at")
            ):
                parts.append("部分身体指标记录已超过 90 天，建议更新后再判断变化。")
        missing = [
            label
            for label, value in (
                ("身高", height),
                ("体重", weight),
                ("体脂", body_fat),
            )
            if value is None
        ]
        if missing and context:
            parts.append(f"尚无{'、'.join(missing)}记录，这部分无法做个人判断。")
        if not context:
            parts.append("可以按你的目标、空闲时间和动作熟悉程度继续调整。")
        return "".join(parts)

    @staticmethod
    def _is_old_record(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            return (date.today() - date.fromisoformat(value)).days > 90
        except ValueError:
            return False

    @staticmethod
    def _direct_task_answer(bundle: AgentExecutionBundle) -> str | None:
        if len(bundle.branch_results) != 1:
            return None
        branch = bundle.branch_results[0]
        result = branch.result or {}
        answer = result.get("task_answer")
        return answer if isinstance(answer, str) and answer.strip() else None

    @staticmethod
    def _direct_failure_answer(
        execution_bundle: AgentExecutionBundle,
    ) -> str | None:
        branch_results = execution_bundle.branch_results
        if not branch_results or any(branch.status != "failed" for branch in branch_results):
            return None
        if any(branch.unpersisted_suggestion for branch in branch_results):
            # The synthesizer can retain useful advice, but must not claim it was saved.
            return None

        error_codes = {branch.error.code for branch in branch_results if branch.error is not None}
        if "VISION_MODEL_BUSY" in error_codes:
            return "视觉评估服务当前繁忙，请稍后重试。"
        if "VISION_ASSESSMENT_INVALID" in error_codes:
            return "视觉模型这次没有返回完整的评估结果，请重新发送照片后重试。"
        if "TRAINING_PLAN_DRAFT_INVALID" in error_codes:
            return "训练计划草稿未通过校验，请调整要求后重试。"
        if "TRAINING_PLAN_DRAFT_NOT_CREATED" in error_codes:
            return "AI 未能创建可确认的训练计划草稿，请稍后重试。"
        if "NUTRITION_TARGET_DRAFT_NOT_CREATED" in error_codes:
            return "饮食目标暂未保存成功，现有目标没有变化。你可以重新生成草稿。"
        messages = list(
            dict.fromkeys(
                branch.error.message for branch in branch_results if branch.error is not None
            )
        )
        return "\n\n".join(messages) or "这次请求暂时无法处理，请核对记录后重试。"

    @staticmethod
    def _direct_read_only_answer(
        execution_bundle: AgentExecutionBundle,
    ) -> str | None:
        if len(execution_bundle.branch_results) != 1:
            return None
        branch = execution_bundle.branch_results[0]
        if branch.task_type not in {"general_question", "structured_data_query"}:
            return None
        if branch.status != "completed" or branch.result is None:
            return None
        if branch.operation_results or branch.confirmation_cards or branch.requires_confirmation:
            return None
        if branch.result.get("query_kind") == "today_training":
            return None
        answer = branch.result.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return None

    @staticmethod
    def _direct_knowledge_answer(
        execution_bundle: AgentExecutionBundle,
    ) -> str | None:
        if len(execution_bundle.branch_results) != 1:
            return None
        branch = execution_bundle.branch_results[0]
        if branch.task_type != "knowledge_retrieval":
            return None
        if branch.status == "completed" and branch.result is not None:
            if branch.result.get("personal_context"):
                # Combine retrieved evidence with current facts, rather than returning
                # generic excerpts for a question about this user's measurements.
                return None
            answer = branch.result.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
        if (
            branch.status == "failed"
            and branch.error is not None
            and branch.error.code == "RAG_UNAVAILABLE"
        ):
            return "知识检索当前未启用，因此我无法可靠回答这个知识问题。"
        return None
