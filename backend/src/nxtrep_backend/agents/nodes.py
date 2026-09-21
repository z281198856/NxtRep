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
        return {
            "execution_bundle": self._safety_validator.validate(execution_bundle),
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

        direct_answer = self._direct_failure_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = direct_today_training_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_knowledge_answer(execution_bundle)
        if direct_answer is None:
            direct_answer = self._direct_read_only_answer(execution_bundle)
        if direct_answer is not None:
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
    def _direct_failure_answer(
        execution_bundle: AgentExecutionBundle,
    ) -> str | None:
        branch_results = execution_bundle.branch_results
        if not branch_results or any(branch.status != "failed" for branch in branch_results):
            return None

        error_codes = {branch.error.code for branch in branch_results if branch.error is not None}
        if "VISION_MODEL_BUSY" in error_codes:
            return "视觉评估服务当前繁忙，请稍后重试。"
        if "VISION_ASSESSMENT_INVALID" in error_codes:
            return "视觉模型这次没有返回完整的评估结果，请重新发送照片后重试。"
        return "这次处理没有完成，请稍后重试。"

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
