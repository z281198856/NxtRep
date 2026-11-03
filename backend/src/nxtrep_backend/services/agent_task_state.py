"""Small, deterministic task continuity layer over the existing conversation.

This module owns conversation state only. It never calls business services, grants
permissions, or treats a model's prose as evidence that a write happened.
"""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from nxtrep_backend.schemas.agent_task import (
    AgentTask,
    AgentTaskCandidate,
    AgentTaskState,
    AgentTaskUpdate,
    TaskTurnPreparation,
    bounded_data,
    clean_entities,
    clean_parameters,
)
from nxtrep_backend.services.agent_input_boundaries import needs_semantic_task_input

READ_TASKS = frozenset(
    {
        "general_question",
        "knowledge_retrieval",
        "structured_data_query",
        "nutrition_analysis",
        "body_assessment",
        "body_progress_comparison",
    }
)
RECORD_TASKS = frozenset({"workout_record_draft"})
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})
_NUMBER = r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+)"
_UNITS = {
    "weight_kg": rf"({_NUMBER})\s*(?:kg|公斤|千克)",
    "sets": rf"({_NUMBER})\s*组",
    "reps": rf"(?:每组\s*)?({_NUMBER})\s*(?:次|个)",
    "amount_g": rf"({_NUMBER})\s*(?:g|克)",
}


def _as_dict(value: Any) -> dict:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def _number(value: str) -> int | str:
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return value
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    total = current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in {"十", "百"}:
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            return value
    return total + current


def _status(task: AgentTask) -> str:
    if task.entities.get("confirmation_id"):
        return "awaiting_confirmation"
    return "collecting" if task.missing_fields else "ready"


def _merge(
    task: AgentTask,
    parameters: dict,
    entities: dict,
    missing: list[str] | None = None,
    invalid: list[str] | None = None,
):
    validated = clean_parameters(parameters)
    validated_entities = clean_entities(entities)
    task.parameters = clean_parameters({**task.parameters, **validated})
    if validated.get("amount_g") is not None:
        task.parameters.pop("_amount_g_input", None)
    task.entities = clean_entities({**task.entities, **validated_entities})
    # Invalid explicit values remain distinct from ordinary absent slots across
    # turns. Only a valid value supplied for that same field resolves the error.
    resolved = {
        name for name, value in {**validated, **validated_entities}.items() if value is not None
    }
    task.invalid_fields = [
        name
        for name in dict.fromkeys([*task.invalid_fields, *(invalid or [])])
        if name not in resolved
    ][:20]
    # A continuation whose router omitted missing_fields cannot erase known gaps.
    # Resolved fields disappear only when actual parameters/entities are supplied.
    outstanding = list(dict.fromkeys([*task.missing_fields, *task.invalid_fields]))
    if missing is not None:
        outstanding = list(dict.fromkeys([*outstanding, *missing]))
    if task.task_type in RECORD_TASKS:
        for name in ("exercise_name", "weight_kg", "sets", "reps"):
            has_exercise = name == "exercise_name" and task.entities.get("exercise_id")
            if name not in task.parameters and not has_exercise and name not in outstanding:
                outstanding.append(name)
    task.missing_fields = [
        name
        for name in outstanding
        if name in task.invalid_fields
        or (
            task.parameters.get(name) is None
            and task.entities.get(name) is None
            and not (name == "exercise_name" and task.entities.get("exercise_id"))
        )
    ][:20]
    changed = [name for name in validated if name in _UNITS]
    if len(changed) == 1:
        task.parameters["last_changed_field"] = changed[0]
    elif len(changed) > 1:
        task.parameters.pop("last_changed_field", None)
    if task.status not in TERMINAL_STATUSES:
        task.status = _status(task)
        task.current_step = "collect_parameters" if task.missing_fields else "propose_action"


def candidate_entities(candidate: AgentTaskCandidate) -> dict:
    if candidate.kind in {"meal", "entry", "meal_item", "food_item"}:
        result = {"entry_id": str(candidate.parent_id or candidate.id)}
        if candidate.item_index is not None:
            result["item_index"] = candidate.item_index
        return result
    if candidate.kind in {"workout_set", "set"}:
        result = {"set_id": str(candidate.id)}
        if candidate.parent_id:
            result["workout_id"] = str(candidate.parent_id)
        return result
    if candidate.kind == "workout_exercise":
        result = {"workout_exercise_id": str(candidate.id)}
        if candidate.parent_id:
            result["workout_id"] = str(candidate.parent_id)
        return result
    mapping = {
        "food": "food_id",
        "exercise": "exercise_id",
        "workout": "workout_id",
        "confirmation": "confirmation_id",
    }
    return {mapping[candidate.kind]: str(candidate.id)} if candidate.kind in mapping else {}


def _candidate_aliases(candidate: AgentTaskCandidate) -> set[str]:
    label = candidate.label.casefold().strip()
    aliases = {label}
    if candidate.kind == "exercise":
        # Equipment is useful only as a disambiguator among actual tool results.
        # Shared terms (e.g. three dumbbell variants) remain ambiguous.
        aliases.update(re.findall(r"杠铃|哑铃|史密斯|器械|自重|上斜|下斜|平板|地板", label))
    if candidate.kind in {"meal", "entry"}:
        for names in (("早餐", "早饭"), ("午餐", "午饭"), ("晚餐", "晚饭"), ("加餐",)):
            if any(name in label for name in names):
                aliases.update(names)
        clock = re.search(r"\d{2}:\d{2}", label)
        if clock:
            aliases.add(clock.group())
    if candidate.kind in {"meal_item", "food_item", "food"}:
        core = label[1:] if label.startswith(("熟", "生")) else label
        aliases.add(core)
        if core.endswith("米饭"):
            aliases.add("米饭")
    return aliases


def _reference_target(text: str) -> str:
    """A trailing preservation clause names exclusions, not operation targets."""
    preserved = re.search(
        r"(?:^|[,，;；])\s*(?:保留|保持|不要改|不要修改|不改|不删除|别动|别删|不要动|不动|留着|"
        r"其(?:他|余)(?:食物|菜品|份量|营养)?(?:都)?不变|(?:先|暂时)?(?:不要|不)(?:确认|保存|启用))",
        text,
    )
    return text[: preserved.start()] if preserved else text


def is_business_removal_request(message: str) -> bool:
    """Recognize explicit removal, leaving negated or unclear requests to the router."""
    for clause in re.split(r"[,，;；。.!！?？\n]|但是|不过|而是", message.casefold()):
        clause = clause.strip()
        action = re.search(
            r"删(?:除|掉|了)?|撤销|作废|移除|去掉|\bdelete\b|\bremove\b|\bvoid\b", clause
        )
        if action and not re.search(
            r"不要|别|先不|暂不|不必|不用|无需|不想|不能|不应|不$|\b(?:not|never|don't)\b",
            clause[: action.start()],
        ):
            return True
        if re.search(r"(?:不要了|不记了)$", clause) or re.search(
            r"(?:刚才|那个|这个|这条|那条).*(?:不要|不记)$", clause
        ):
            return True
    return False


def _meal_portion_correction(text: str):
    text = re.sub(r"^(?:把)?(?:刚才(?:的|那个)?|那个|这个)?", "", _reference_target(text))
    match = re.fullmatch(
        rf"(?P<name>.+?)(?:的)?(?:份量|重量)?(?:也)?(?:改成|改为|改回|调整为)"
        rf"\s*(?P<quantity>{_NUMBER}\s*(?:克|g))",
        text,
    )
    if match and not re.search(r"和|、|以及|还有", match["name"]):
        return match
    return None


def _resolve_candidate(candidates: list[AgentTaskCandidate], text: str) -> list[AgentTaskCandidate]:
    text = _reference_target(text)
    scored = []
    for candidate in candidates:
        score = max(
            (len(alias) for alias in _candidate_aliases(candidate) if alias and alias in text),
            default=0,
        )
        if score:
            scored.append((candidate, score))
    if not scored:
        portion = _meal_portion_correction(text)
        if portion:
            return [
                candidate
                for candidate in candidates
                if candidate.kind in {"meal_item", "food_item"}
                and portion["name"] in candidate.label.casefold()
            ]
        return []
    if re.search(r"和|、|以及", text):
        return [candidate for candidate, _ in scored]
    longest = max(score for _, score in scored)
    return [candidate for candidate, score in scored if score == longest]


class AgentTaskCapacityError(RuntimeError):
    """Starting another task would discard a still-paused task."""


class TaskStateManager:
    """Pure helpers; persistence and actual confirmation status stay in existing services."""

    @staticmethod
    def load(raw: Any) -> AgentTaskState:
        if isinstance(raw, AgentTaskState):
            state = raw.model_copy(deep=True)
        else:
            try:
                state = AgentTaskState.model_validate(raw or {})
            except (ValidationError, TypeError):
                # Old or invalid state must never supply an invented business target.
                return AgentTaskState()
        for task in TaskStateManager.tasks(state):
            if (
                not task.candidates
                and task.status == "collecting"
                and task.current_step in {"clarify_target", "collect_parameters"}
                and task.last_tool_result.get("status") in {"needs_review", "needs_input"}
            ):
                # Recover choices from older turns that saved the raw tool result
                # but could not adapt exercise/workout candidates into Task State.
                task.candidates = TaskStateManager._candidates(
                    task.last_tool_result.get("candidates") or []
                )
                if task.candidates and set(task.missing_fields) & {"exercise_id", "workout_id"}:
                    task.missing_fields = [
                        field for field in task.missing_fields
                        if field not in {"exercise_id", "workout_id"}
                    ] + ["selection"]
        return state

    @staticmethod
    def tasks(state: AgentTaskState) -> list[AgentTask]:
        return [task for task in (state.active_task, state.suspended_task, *state.suspended_tasks)
                if task is not None]

    @classmethod
    def displayed_selection(cls, raw: Any, message: str, messages) -> dict:
        """Resolve only a literal ordinal against a verified, actually displayed list."""
        task = cls.load(raw).active_task
        text = message.strip().strip("。.!！?？,， ")
        ordinal = re.fullmatch(rf"(?:选|选择|就选)?第?\s*({_NUMBER})\s*(?:个|条|组)?", text)
        if not task or not task.candidates or not ordinal:
            return {}
        if "selection" not in task.missing_fields and task.current_step != "clarify_target":
            return {}
        number = _number(ordinal[1])
        if not str(number).isdigit():
            return {}
        for message in reversed(messages):
            role = message.get("role") if isinstance(message, dict) else message.role
            if role != "assistant":
                continue
            content = message.get("content", "") if isinstance(message, dict) else message.content
            rows, invalid = {}, False
            for line in content.splitlines():
                numbered = re.match(r"^\s*(?:[-*]\s*)?(\d+)[.、．)）]\s*(.+)$", line)
                if not numbered:
                    continue
                matches = [candidate for candidate in task.candidates
                           if candidate.label in numbered[2]]
                if len(matches) != 1 or int(numbered[1]) in rows:
                    invalid = True
                    break
                rows[int(numbered[1])] = matches[0]
            if rows:
                if invalid or sorted(rows) != list(range(1, len(rows) + 1)):
                    return {}
                selected = rows.get(int(number))
                if selected is not None and len({c.id for c in rows.values()}) == len(rows):
                    return {"source": "last_displayed_list", "label": selected.label,
                            "entities": candidate_entities(selected)}
                return {}
        return {}

    @staticmethod
    def replace_task(state: AgentTaskState, replacement: AgentTask) -> None:
        for name in ("active_task", "suspended_task"):
            task = getattr(state, name)
            if task and task.task_id == replacement.task_id:
                setattr(state, name, replacement)
                return
        state.suspended_tasks = [replacement if t.task_id == replacement.task_id else t
                                 for t in state.suspended_tasks]

    @staticmethod
    def _suspend(state: AgentTaskState, task: AgentTask) -> None:
        paused = [t for t in (state.suspended_task, *state.suspended_tasks)
                  if t and t.task_id != task.task_id]
        if len(paused) >= 5:
            raise AgentTaskCapacityError(
                "已有五个暂停任务，请先完成或取消一个任务，再开始新的任务。"
            )
        task.status = "suspended"
        state.suspended_task, state.suspended_tasks = task, paused

    @staticmethod
    def resume_candidate(state: AgentTaskState, update: AgentTaskUpdate,
                         task_type: str) -> AgentTask | None:
        paused = [t for t in (state.suspended_task, *state.suspended_tasks) if t]
        if update.resume_task_id:
            return next((t for t in TaskStateManager.tasks(state)
                         if t.task_id == update.resume_task_id), None)
        matches = [t for t in paused if t.task_type == task_type]
        if len(matches) == 1:
            return matches[0]
        return paused[0] if len(paused) == 1 else None

    @classmethod
    def _resume(cls, state: AgentTaskState, selected: AgentTask) -> AgentTask:
        remaining = [t for t in (state.suspended_task, *state.suspended_tasks)
                     if t and t.task_id != selected.task_id]
        state.suspended_task = remaining[0] if remaining else None
        state.suspended_tasks = remaining[1:]
        if (state.active_task and state.active_task.task_id != selected.task_id
                and state.active_task.status not in TERMINAL_STATUSES):
            cls._suspend(state, state.active_task)
        if selected.status not in TERMINAL_STATUSES:
            selected.status = _status(selected)
        state.active_task = selected
        return selected

    @classmethod
    def prepare_turn(cls, raw: Any, message: str) -> TaskTurnPreparation:
        state = cls.load(raw)
        result = TaskTurnPreparation(state=state)
        text = message.strip().casefold().strip("。.!！?？,， ")
        active = state.active_task
        if re.fullmatch(
            r"(?:继续|恢复|回到)(?:刚才|之前|上一个|原来)?(?:的)?(?:训练|任务|计划|记录)?", text
        ):
            if state.suspended_task and not state.suspended_tasks:
                restored = cls._resume(state, state.suspended_task)
                result.transition, result.handled = "resume", True
                result.parameters, result.entities = (
                    restored.parameters.copy(),
                    restored.entities.copy(),
                )
            elif (not state.suspended_task and active
                  and active.status in {"awaiting_confirmation", "completed"}):
                result.transition, result.handled = "resume", True
                result.parameters, result.entities = (
                    active.parameters.copy(),
                    active.entities.copy(),
                )
            return result
        if active is None:
            return result
        if active.parameters.get("action") == "change_date":
            if text in {"全部", "都改", "全部改", "整天", "全部移过去", "都移过去"}:
                active.parameters["scope"] = "day"
                active.parameters.pop("meal_type", None)
                active.entities.pop("entry_id", None)
                active.entities.pop("meal_id", None)
                active.entities.pop("item_index", None)
                active.missing_fields = [f for f in active.missing_fields if f != "selection"]
                result.parameters = {"scope": "day"}
                result.transition, result.handled = "continue", True
                return result
            if text in {"是", "是的", "对", "对的", "没错"}:
                # Acknowledgement preserves dates but never selects one ambiguous meal
                # or approves a business write.
                result.transition, result.handled = "continue", True
                return result
        if text in {"不是这个", "不是那个", "不对不是这个", "不对，不是这个", "找错了"}:
            result.clarification_required = True
            active.status, active.current_step = "collecting", "clarify_target"
            if "selection" not in active.missing_fields:
                active.missing_fields.append("selection")
            if len(active.candidates) == 1:
                active.candidates = []
            return result
        cancelled = re.fullmatch(
            r"(?:算了(?:[,， ]*(?:不记了|不记录了|不要了|取消|刚才那条不要了))?|"
            r"取消(?:这个|当前|刚才的)?(?:任务|记录|草稿)?|不记了|不记录了|"
            r"撤销(?:刚才|上一条|这条)?(?:的)?(?:记录|任务|草稿)?|刚才那条不要了)",
            text,
        )
        if cancelled:
            result.transition = "cancel"
            result.entities = active.entities.copy()
            if not active.entities.get("confirmation_id") and any(
                candidate.kind == "confirmation" for candidate in active.candidates
            ):
                # Recovered proposals exist; choosing which card to cancel is a
                # business action, never a pure task-state cancellation.
                active.status, active.current_step = "awaiting_confirmation", "clarify_target"
                if "selection" not in active.missing_fields:
                    active.missing_fields.append("selection")
                result.clarification_required = True
                result.requires_business_action = True
                return result
            if active.status in {"collecting", "ready", "failed"} and not active.entities.get(
                "confirmation_id"
            ):
                active.status, active.current_step = "cancelled", "cancelled"
                active.missing_fields = []
                result.handled = True
            else:
                # Cancelling state is not deleting a persisted record or a pending card.
                result.requires_business_action = True
            return result

        if needs_semantic_task_input(message.casefold()):
            # Preserve the original state for semantic routing. A candidate name
            # inside a question is not consent to continue its pending mutation.
            return result
        removal = is_business_removal_request(text)
        reference_action = (
            bool(re.search(r"改|那个|这个|刚才|第.+个", text))
            or removal or "selection" in active.missing_fields
        )
        if active.candidates and reference_action:
            candidates = active.candidates
            target_text = _reference_target(text)
            aliases = sorted(
                {alias for candidate in candidates for alias in _candidate_aliases(candidate)},
                key=len, reverse=True,
            )
            choice = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
            explicit_choice = bool(re.fullmatch(
                rf"(?:选(?:择)?|就(?:选|用)?|用|是|要)?\s*{choice}(?:这个|那个|的|吧|就行)?",
                text,
            ))
            ordinal = re.search(rf"第\s*({_NUMBER})\s*(?:个|条|组)", target_text)
            selected = None
            if ordinal:
                index = _number(ordinal.group(1))
                kinds = {candidate.kind for candidate in candidates}
                if len(kinds) == 1 and str(index).isdigit() and 1 <= int(index) <= len(candidates):
                    selected = candidates[int(index) - 1]
                else:
                    result.clarification_required = True
            else:
                matches = _resolve_candidate(candidates, target_text)
                if re.search(r"整顿|整餐|整份(?:午饭|晚饭|早餐|餐食)", target_text):
                    matches = [c for c in candidates if c.kind in {"meal", "entry"}]
                if len(matches) == 1:
                    selected = matches[0]
                elif len(candidates) == 1 and re.fullmatch(
                    r"(?:把)?(?:刚才(?:的|那[个条])?|这[个条]|那[个条]|上一个)"
                    r"(?:删(?:除|掉)?(?:了)?|撤销|作废|移除|去掉)?",
                    target_text,
                ):
                    selected = candidates[0]
                elif (
                    re.search(r"那个|这个|刚才的", target_text) or removal
                    or explicit_choice and len(matches) > 1
                ):
                    result.clarification_required = True
                    if explicit_choice and "selection" in active.missing_fields:
                        result.handled, result.transition = True, "continue"
            if selected:
                result.selection = selected
                result.entities = candidate_entities(selected)
                if "selection" in active.missing_fields and (
                    explicit_choice
                    or re.fullmatch(rf"第\s*({_NUMBER})\s*(?:个|条|组)", text)
                ):
                    result.handled = True
                active.entities = clean_entities({**active.entities, **result.entities})
                if selected.kind in {"meal", "entry"}:
                    active.entities.pop("item_index", None)
                    active.parameters.pop("food_name", None)
                elif selected.kind in {"meal_item", "food_item"}:
                    active.parameters["food_name"] = selected.label
                elif selected.kind == "exercise":
                    active.parameters["exercise_name"] = selected.label
                    if result.handled:
                        result.parameters["exercise_name"] = selected.label
                active.missing_fields = [f for f in active.missing_fields if f != "selection"]

        # Only syntactically complete quantity replies are deterministic. A sentence
        # about two exercises, negation, food calories, etc. remains with the planner.
        correction = bool(re.match(r"(?:不对|不是|改成|改为|改回|应该是|是)", text))
        quantity_text = re.sub(
            r"^(?:不对[,， ]*(?:是)?|不是[,， ]*|改成|改为|改回|应该是|是)",
            "",
            _reference_target(text),
        )
        if result.selection and not result.clarification_required:
            aliases = sorted(_candidate_aliases(result.selection), key=len, reverse=True)
            label = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
            named_correction = re.fullmatch(
                rf"(?:把)?(?:刚才(?:的|那个)?|那个|这个)?{label}(?:的)?"
                rf"(?:份量|重量)?(?:也)?(?:改成|改为|改回|调整为)\s*(.+)",
                _reference_target(text),
            )
            if named_correction:
                correction = True
                quantity_text = named_correction.group(1)
            elif result.selection.kind in {"meal_item", "food_item"}:
                portion = _meal_portion_correction(text)
                if portion and portion["name"] in result.selection.label.casefold():
                    correction = True
                    quantity_text = portion["quantity"]
        extracted = {}
        remaining = quantity_text
        for field, pattern in _UNITS.items():
            matches = list(re.finditer(pattern, quantity_text))
            if len(matches) == 1:
                extracted[field] = _number(matches[0].group(1))
                remaining = re.sub(pattern, "", remaining)
        remaining = re.sub(r"(?:每组|每个|做了|一共|共|了|和|[,，、;；\s])", "", remaining)
        if remaining:
            extracted = {}
        if not extracted and re.fullmatch(_NUMBER, quantity_text):
            possible = [name for name in active.missing_fields if name in _UNITS]
            if correction:
                recent = active.parameters.get("last_changed_field")
                possible = (
                    [recent]
                    if recent in _UNITS
                    else [name for name in _UNITS if name in active.parameters]
                )
            if len(possible) == 1:
                extracted[possible[0]] = _number(quantity_text)
            else:
                result.clarification_required = True
        extracted = clean_parameters(extracted)
        if extracted:
            result.parameters = extracted
            result.transition = (
                "correct" if correction or active.status in TERMINAL_STATUSES else "continue"
            )
            _merge(active, extracted, result.entities)
        elif result.selection:
            result.transition = "correct" if active.status in TERMINAL_STATUSES else "continue"
        return result

    @classmethod
    def apply_plan(
        cls, raw: Any, task_type: str, update: AgentTaskUpdate | dict | None = None
    ) -> AgentTaskState:
        state = cls.load(raw)
        update = (
            update
            if isinstance(update, AgentTaskUpdate)
            else AgentTaskUpdate.model_validate(update or {})
        )
        active = state.active_task
        if task_type in READ_TASKS:
            if active and active.status not in TERMINAL_STATUSES:
                if active.status != "suspended":
                    cls._suspend(state, active)
                state.active_task = None
            return state
        if (
            active is None and state.suspended_task
            and update.transition in {"continue", "correct"}
        ):
            # A preceding query can suspend the active task within this same plan.
            # Explicit continuation must resolve that task, not start an empty one.
            update = update.model_copy(update={"transition": "resume"})
        if update.transition == "resume" and state.suspended_task:
            selected = cls.resume_candidate(state, update, task_type)
            if selected is None:
                if active and active.status not in TERMINAL_STATUSES:
                    cls._suspend(state, active)
                state.active_task = AgentTask(task_type=task_type, missing_fields=["selection"],
                    current_step="clarify_task", candidates=[AgentTaskCandidate(kind="task",
                        id=t.task_id, label=str(t.parameters.get("exercise_name")
                            or t.parameters.get("food_name") or t.task_type))
                        for t in (state.suspended_task, *state.suspended_tasks) if t])
                return state
            active = cls._resume(state, selected)
        elif update.transition == "cancel":
            # Executed work and confirmation cards require existing business tools.
            if (
                active
                and active.status in {"collecting", "ready"}
                and not active.entities.get("confirmation_id")
            ):
                active.status, active.current_step = "cancelled", "cancelled"
                active.missing_fields = []
            return state

        previous_exercise = active.parameters.get("exercise_name") if active else None
        next_exercise = update.parameters.get("exercise_name")
        choosing_exercise = bool(
            active and active.task_type == task_type == "workout_record_draft"
            and active.status == "collecting" and "selection" in active.missing_fields
            and update.transition in {"continue", "correct"}
            and "selection" not in update.missing_fields
            and any(
                candidate.kind == "exercise"
                and str(candidate.id) == update.entities.get("exercise_id")
                for candidate in active.candidates
            )
        )
        exercise_changed = bool(
            next_exercise and previous_exercise and next_exercise != previous_exercise
            and not choosing_exercise
            and update.transition != "correct"
            and not (active and any(
                update.entities.get(key) and update.entities[key] == active.entities.get(key)
                for key in ("exercise_id", "workout_exercise_id")
            ))
        )

        def family(kind: str) -> str:
            if kind.startswith("nutrition_entry_") or kind == "nutrition_record_draft":
                return "meal"
            if kind.startswith("workout_"):
                return "workout"
            return kind

        if update.transition == "correct":
            grounded = [previous for previous in cls.tasks(state)
                        if family(previous.task_type) == family(task_type) and any(
                            update.entities.get(key) == value
                            for key, value in previous.entities.items() if key.endswith("_id")
                        )]
            if len(grounded) == 1 and grounded[0] is not active:
                # An explicit trusted entity can identify an earlier paused task.
                active = cls._resume(state, grounded[0])
        changed_family = active is not None and family(active.task_type) != family(task_type)
        new = (
            active is None
            or update.transition == "new"
            or changed_family
            or (active.status == "cancelled" and update.transition != "resume")
            or exercise_changed
        )
        incompatible_session_ids = set()
        if new:
            inherited_parameters, inherited_entities = {}, {}
            inherited_candidates = (
                [
                    candidate.model_copy(deep=True)
                    for candidate in active.candidates
                    if candidate.kind == "confirmation"
                ]
                if active and task_type == "confirmation_cancel"
                else []
            )
            if active and exercise_changed:
                inherited_parameters = {
                    key: value
                    for key, value in active.parameters.items()
                    if key in {"date", "workout_date", "timezone", "muscle_group"}
                }
                previous_date = (
                    active.parameters.get("workout_date") or active.parameters.get("date")
                )
                next_date = update.parameters.get("workout_date") or update.parameters.get("date")
                inherited_entities = {
                    key: value
                    for key, value in active.entities.items()
                    if key in {"workout_id", "session_id"}
                } if next_date is None or str(next_date) == str(previous_date) else {}
                if next_date is not None:
                    inherited_parameters.pop("date", None)
                    inherited_parameters.pop("workout_date", None)
                    if str(next_date) != str(previous_date):
                        incompatible_session_ids = {value for key, value in active.entities.items()
                                                    if key in {"workout_id", "session_id"}}
            elif active and active.status not in TERMINAL_STATUSES:
                cls._suspend(state, active)
            active = AgentTask(
                task_type=task_type,
                parameters=inherited_parameters,
                entities=inherited_entities,
                candidates=inherited_candidates,
            )
            state.active_task = active
        else:
            active.task_type = task_type
            if update.transition == "correct":
                active.status = "collecting"
        if update.reference_entities:
            active.reference_entities = update.reference_entities.copy()
        entities = update.entities.copy()
        for key in ("workout_id", "session_id"):
            if entities.get(key) in incompatible_session_ids:
                entities.pop(key, None)
        selected_candidates = [
            candidate for candidate in active.candidates
            if (identity := candidate_entities(candidate))
            and all(entities.get(key) == value for key, value in identity.items())
            and not (
                candidate.kind in {"meal", "entry"} and "item_index" in entities
            )
        ]
        if len(selected_candidates) == 1 and "selection" not in update.missing_fields:
            selected = selected_candidates[0]
            identity = candidate_entities(selected)
            if any(active.entities.get(key) != value for key, value in identity.items()):
                active.entities.pop("version", None)
            # The model chose a real candidate. A previous focus is not a conflict
            # with a verified local target switch; arbitrary IDs remain conflicts.
            active.entities.update(identity)
            if selected.kind in {"meal", "entry"}:
                active.entities.pop("item_index", None)
                active.parameters.pop("food_name", None)
            elif selected.kind in {"meal_item", "food_item"}:
                active.parameters["food_name"] = selected.label
            active.missing_fields = [f for f in active.missing_fields if f != "selection"]
        conflicts = False
        if not new:
            for key, value in list(entities.items()):
                if (key.endswith("_id") or key == "item_index") and key in active.entities:
                    if active.entities[key] != value:
                        conflicts = True
                        entities.pop(key)
        missing = list(update.missing_fields)
        selected_exercises = [
            candidate for candidate in active.candidates
            if candidate.kind == "exercise"
            and str(candidate.id) == entities.get("exercise_id")
        ]
        if len(selected_exercises) == 1 and "selection" not in missing:
            active.parameters["exercise_name"] = selected_exercises[0].label
            active.missing_fields = [
                field for field in active.missing_fields
                if field not in {"selection", "exercise_id"}
            ]
        for field in update.invalid_fields:
            active.parameters.pop(field, None)
            if field not in missing:
                missing.append(field)
        if conflicts and "selection" not in missing:
            missing.append("selection")
        # Waiting for the user's promised details is a turn-level preference,
        # not a permanent slot that blocks all subsequent continuations.
        active.parameters.pop("awaiting_user_details", None)
        active.missing_fields = [
            field for field in active.missing_fields if field != "training_details"
        ]
        missing = [field for field in missing if field != "training_details"]
        _merge(active, update.parameters, entities, missing, update.invalid_fields)
        if (
            task_type in {"workout_record_draft", "training_plan_draft"}
            and active.parameters.get("awaiting_user_details") is True
            and not active.invalid_fields
            and "selection" not in active.missing_fields
            and not active.entities.get("confirmation_id")
        ):
            if not active.missing_fields:
                active.missing_fields = ["training_details"]
                active.status = "collecting"
            active.current_step = "await_user_details"
        if conflicts:
            active.current_step = "clarify_target"
        return state

    @classmethod
    def commit_results(
        cls,
        raw: Any,
        tool_results: list[Any] | None = None,
        confirmation_cards: list[Any] | None = None,
        *,
        last_tool_call: dict | None = None,
        results: list[Any] | None = None,
        cards: list[Any] | None = None,
    ) -> AgentTaskState:
        state = cls.load(raw)
        task = state.active_task
        if task is None:
            return state
        if last_tool_call:
            task.last_tool_call = bounded_data(last_tool_call)
        for original in tool_results or results or []:
            payload = _as_dict(original)
            if not payload:
                continue
            status = payload.get("status")
            task.last_tool_result = bounded_data(payload)
            selected = _as_dict(
                payload.get("selected_entry")
                or payload.get("selected_set")
                or payload.get("selected_record")
            )
            if selected and status == "available":
                task.entities = clean_entities({**task.entities, **selected})
                task.parameters = clean_parameters(
                    {
                        **task.parameters,
                        **{
                            key: value
                            for key, value in selected.items()
                            if key in {"date", "exercise_name", "weight_kg", "reps", "meal_type"}
                        },
                    }
                )
                task.candidates = cls._candidates([selected])
                task.missing_fields = [
                    field for field in task.missing_fields if field != "selection"
                ]
            elif status == "needs_input":
                task.candidates = cls._candidates(payload.get("candidates", []))
                task.missing_fields = list(
                    dict.fromkeys(payload.get("missing_fields") or ["selection"])
                )[:20]
                task.status, task.current_step = "collecting", "collect_parameters"
            elif status == "needs_review":
                task.candidates = cls._candidates(payload.get("candidates", []))
                task.status, task.current_step = "collecting", "clarify_target"
                if "selection" not in task.missing_fields:
                    task.missing_fields.append("selection")
            elif payload.get("success") is True or status == "completed":
                data = _as_dict(payload.get("data"))
                task.entities = clean_entities({**task.entities, **payload, **data})
                task.status, task.current_step = "completed", "completed"
                task.missing_fields = []
            elif status == "failed" or payload.get("success") is False:
                task.status, task.current_step = "failed", "recover_or_explain"
            confirmation = payload.get("confirmation")
            if confirmation:
                cls._commit_card(task, _as_dict(confirmation))
        for original in confirmation_cards or cards or []:
            cls._commit_card(task, _as_dict(original))
        return state

    @staticmethod
    def _commit_card(task: AgentTask, card: dict):
        entities = clean_entities({"confirmation_id": card.get("confirmation_id")})
        if not entities:
            return
        task.entities = clean_entities({**task.entities, **entities, **_as_dict(card.get("after"))})
        if card.get("operation_type") == "workout_record_create":
            request = _as_dict(_as_dict(card.get("after")).get("request"))
            task.entities = clean_entities({**task.entities, **request})
            task.parameters = clean_parameters({
                **task.parameters,
                **{key: value for key, value in request.items() if key in {
                    "exercise_name", "weight_kg", "sets", "reps", "workout_date", "started_at",
                }},
            })
        task.last_tool_result = bounded_data({"confirmation": card})
        status = card.get("status")
        if status in {"pending", "confirmation_required"}:
            task.status, task.current_step = "awaiting_confirmation", "user_confirmation"
            task.missing_fields = []
        elif status in {"approved", "applied", "succeeded"}:
            # Business IDs are resolved from the authoritative applied result by caller.
            task.status, task.current_step = "completed", "completed"
            task.missing_fields = []
        elif status in {"cancelled", "rejected", "expired"}:
            task.status, task.current_step = "cancelled", "cancelled"
            task.missing_fields = []

    @staticmethod
    def _candidates(rows: list) -> list[AgentTaskCandidate]:
        result = []
        if not isinstance(rows, list):
            return result
        for raw in rows[:20]:
            row = _as_dict(raw)
            try:
                if row.get("workout_exercise_id"):
                    identifier = UUID(str(row["workout_exercise_id"]))
                    result.append(
                        AgentTaskCandidate(
                            kind="workout_exercise",
                            id=identifier,
                            parent_id=UUID(str(row["workout_id"])),
                            label=str(row.get("exercise_name") or "训练动作")[:160],
                        )
                    )
                elif row.get("set_id"):
                    result.append(
                        AgentTaskCandidate(
                            kind="workout_set",
                            id=UUID(str(row["set_id"])),
                            parent_id=UUID(str(row["workout_id"])),
                            label=(
                                f"{row.get('exercise_name', '训练')}第{row.get('set_index', '?')}组"
                            ),
                        )
                    )
                elif row.get("exercise_id"):
                    result.append(AgentTaskCandidate(
                        kind="exercise", id=UUID(str(row["exercise_id"])),
                        label=str(row.get("exercise_name") or "训练动作")[:160],
                    ))
                elif row.get("entry_id"):
                    identifier = UUID(str(row["entry_id"]))
                    meal_name = {
                        "breakfast": "早餐",
                        "lunch": "午饭",
                        "dinner": "晚饭",
                        "snack": "加餐",
                        "other": "这餐",
                    }.get(row.get("meal_type"), "这餐")
                    result.append(
                        AgentTaskCandidate(
                            kind="meal",
                            id=identifier,
                            label=f"整顿{meal_name}",
                        )
                    )
                    for index, item in enumerate(row.get("items", [])[:18]):
                        result.append(
                            AgentTaskCandidate(
                                kind="meal_item",
                                id=identifier,
                                parent_id=identifier,
                                item_index=item.get("item_index", index),
                                label=str(item.get("name") or "食物")[:160],
                            )
                        )
                elif row.get("food_id"):
                    result.append(AgentTaskCandidate(
                        kind="food", id=UUID(str(row["food_id"])),
                        label=str(row.get("name") or row.get("food_name") or "自定义食品")[:160],
                    ))
                elif row.get("workout_id"):
                    result.append(AgentTaskCandidate(
                        kind="workout", id=UUID(str(row["workout_id"])),
                        label=f"{row.get('date', '')}的训练"[:160],
                    ))
                elif row.get("kind") and row.get("id"):
                    result.append(AgentTaskCandidate.model_validate(row))
            except (ValidationError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return result[:20]
