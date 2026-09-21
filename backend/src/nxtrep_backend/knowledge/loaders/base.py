from typing import Protocol

from nxtrep_backend.knowledge.schemas import (
    KnowledgeLoadRequest,
    ParsedDocument,
)


class KnowledgeDocumentLoadError(RuntimeError):
    """原始知识文档无法被可靠读取。"""


class KnowledgeDocumentLoader(Protocol):
    """所有知识文档Loader必须遵循的统一接口。"""

    @property
    def supported_content_types(self) -> frozenset[str]:
        """返回当前Loader支持的MIME类型。"""
        ...

    def load(
        self,
        request: KnowledgeLoadRequest,
    ) -> ParsedDocument:
        """读取原始文件并返回统一的解析结果。"""
        ...
