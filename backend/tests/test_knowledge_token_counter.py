import pytest

from nxtrep_backend.knowledge.token_counter import (
    TiktokenTokenCounter,
    TokenCounter,
)


class CharacterTokenCounter:
    @property
    def name(self) -> str:
        return "characters:v1"

    def count(self, text: str) -> int:
        return len(text)


def count_with_contract(
    counter: TokenCounter,
    text: str,
) -> int:
    return counter.count(text)


def test_tiktoken_counter_reports_name_and_empty_text() -> None:
    counter = TiktokenTokenCounter()

    assert counter.name == "tiktoken:cl100k_base"
    assert counter.count("") == 0


def test_tiktoken_counter_is_positive_and_deterministic_for_chinese() -> None:
    counter = TiktokenTokenCounter()
    text = "成年人每周应进行规律身体活动。"

    first_count = counter.count(text)
    second_count = counter.count(text)

    assert first_count > 0
    assert first_count == second_count


def test_tiktoken_counter_allows_special_marker_text() -> None:
    counter = TiktokenTokenCounter()

    assert counter.count("Literal marker: <|endoftext|>") > 0


def test_token_counter_protocol_accepts_test_double() -> None:
    counter = CharacterTokenCounter()

    assert count_with_contract(counter, "abc") == 3


def test_tiktoken_counter_rejects_unknown_encoding() -> None:
    with pytest.raises(ValueError, match="Unknown encoding"):
        TiktokenTokenCounter("not-a-real-encoding")
