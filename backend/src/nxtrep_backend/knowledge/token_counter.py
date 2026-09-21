from typing import Protocol

import tiktoken


class TokenCounter(Protocol):
    """为Chunker提供统一的Token统计接口。"""

    @property
    def name(self) -> str:
        """返回统计器名称和版本。"""
        ...

    def count(self, text: str) -> int:
        """返回文本的大致Token数量。"""
        ...


class TiktokenTokenCounter:
    """使用tiktoken进行稳定、可重复的Token统计。"""

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self._encoding_name = encoding_name
        self._encoding = tiktoken.get_encoding(encoding_name)

    @property
    def name(self) -> str:
        return f"tiktoken:{self._encoding_name}"

    def count(self, text: str) -> int:
        if not text:
            return 0

        token_ids = self._encoding.encode(
            text,
            disallowed_special=(),
        )

        return len(token_ids)
