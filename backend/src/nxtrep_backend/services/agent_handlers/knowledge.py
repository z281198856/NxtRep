import re

from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
    KnowledgeTopic,
)
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentCitation,
)
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.knowledge_retrieval import KnowledgeRetrievalService

_SUSPICIOUS_EVIDENCE_MARKERS = (
    "rag_override",
    "ignore previous instructions",
    "ignore system instructions",
    "reveal the system prompt",
    "忽略系统",
    "忽略以上",
    "管理员权限",
    "绕过系统",
    "不可信内容测试样本",
    "回答者必须",
)


class KnowledgeRetrievalBranchHandler:
    """Answer read-only knowledge questions from reviewed evidence only."""

    def __init__(
        self,
        service: KnowledgeRetrievalService,
        *,
        candidate_k: int,
        top_k: int,
    ) -> None:
        self._service = service
        self._candidate_k = candidate_k
        self._top_k = top_k

    async def execute(
        self,
        branch_input: AgentBranchInput,
    ) -> AgentBranchResult:
        task = branch_input.task
        if task.task_type != "knowledge_retrieval":
            raise ValueError("KnowledgeRetrievalBranchHandler requires a knowledge task")

        missing_fields = list(dict.fromkeys(task.missing_fields))
        if missing_fields:
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                missing_fields=missing_fields,
            )

        hits = await self._service.retrieve(
            KnowledgeRetrievalRequest(
                query=branch_input.message,
                topic=self._infer_topic(branch_input.message),
                locale="zh-CN",
                candidate_k=self._candidate_k,
                top_k=self._top_k,
            )
        )

        if not hits:
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="completed",
                result={
                    "answer": (
                        "知识库没有检索到足够依据，因此我暂时不能可靠回答这个问题。"
                        "我不会用模型记忆补全未经审核的规则。"
                    ),
                    "evidence_status": "no_evidence",
                },
            )

        citations = self._build_citations(hits)
        excerpts = self._safe_excerpts(hits)
        source_lines = [f"- {citation.label}" for citation in citations]
        answer_parts = [
            "知识库检索到以下只读依据：",
            *[f"- {excerpt}" for excerpt in excerpts],
            "来源：",
            *source_lines,
            "这些是通用资料；如有明显不适或紧急症状，应停止训练并寻求专业帮助。",
        ]

        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status="completed",
            result={
                "answer": "\n".join(answer_parts),
                "evidence_status": "available",
                "evidence_count": len(hits),
            },
            citations=citations,
        )

    @staticmethod
    def _infer_topic(message: str) -> KnowledgeTopic:
        normalized = message.casefold()
        if any(
            marker in normalized
            for marker in (
                "蛋白质",
                "营养",
                "饮食",
                "热量",
                "餐",
                "protein",
                "nutrition",
                "diet",
                "calorie",
                "meal",
            )
        ):
            return "nutrition"
        if any(
            marker in normalized
            for marker in (
                "停止",
                "胸痛",
                "眩晕",
                "昏厥",
                "疼痛",
                "受伤",
                "危险",
                "安全提示",
                "stop",
                "chest pain",
                "dizzy",
                "injury",
                "safety",
            )
        ):
            return "safety"
        if any(
            marker in normalized
            for marker in (
                "深蹲",
                "卧推",
                "硬拉",
                "动作",
                "姿势",
                "squat",
                "deadlift",
                "bench press",
                "exercise form",
            )
        ):
            return "exercise"
        if "nxtrep" in normalized and any(
            marker in normalized
            for marker in ("怎么用", "如何使用", "功能", "how to use", "feature")
        ):
            return "product_help"
        return "training"

    @classmethod
    def _safe_excerpts(
        cls,
        hits: tuple[KnowledgeRetrievalHit, ...],
    ) -> list[str]:
        excerpts: list[str] = []
        total_length = 0

        for hit in hits:
            segments = re.split(
                r"(?<=[。！？])|(?<=[.!?])\s+|\n+",
                hit.content,
            )
            safe_segments = [
                segment.strip()
                for segment in segments
                if segment.strip() and not cls._is_suspicious_evidence(segment)
            ]
            if not safe_segments:
                continue
            excerpt = " ".join(safe_segments[:3])
            if len(excerpt) > 420:
                excerpt = excerpt[:417].rstrip() + "..."
            if total_length + len(excerpt) > 900:
                break
            excerpts.append(excerpt)
            total_length += len(excerpt)
            if len(excerpts) == 3:
                break

        return excerpts or ["已找到相关资料，但安全过滤后没有可直接展示的原文摘录。"]

    @staticmethod
    def _is_suspicious_evidence(value: str) -> bool:
        normalized = value.casefold()
        return any(marker in normalized for marker in _SUSPICIOUS_EVIDENCE_MARKERS)

    @staticmethod
    def _build_citations(
        hits: tuple[KnowledgeRetrievalHit, ...],
    ) -> list[AgentCitation]:
        grouped: dict[tuple[str, int], dict[str, object]] = {}
        for hit in hits:
            key = (hit.source_key, hit.source_version)
            source = grouped.setdefault(
                key,
                {
                    "title": hit.source_title,
                    "section": hit.section_path,
                    "pages": set(),
                },
            )
            pages = source["pages"]
            assert isinstance(pages, set)
            pages.update(hit.page_numbers)

        citations: list[AgentCitation] = []
        for (source_key, source_version), source in grouped.items():
            label_parts = [str(source["title"]), f"版本 {source_version}"]
            if source["section"]:
                label_parts.append(str(source["section"]))
            pages = sorted(source["pages"])
            if len(pages) == 1:
                label_parts.append(f"第{pages[0]}页")
            elif pages:
                label_parts.append(f"第{pages[0]}-{pages[-1]}页")
            citations.append(
                AgentCitation(
                    source_type="knowledge",
                    source_id=f"{source_key}@{source_version}",
                    label=" / ".join(label_parts),
                )
            )
        return citations
