"""LLM client unit tests (no network)."""

from __future__ import annotations

import pytest

from medagent.llm import LLMError, extract_json
from medagent.types import LLMResult, Usage


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    fenced = "Here you go:\n```json\n{\"answer\": \"yes\"}\n```"
    assert extract_json(fenced) == {"answer": "yes"}


def test_extract_json_no_object_raises():
    with pytest.raises(LLMError):
        extract_json("no json at all")


def test_usage_add():
    usage = Usage(prompt_tokens=10, completion_tokens=5)
    usage.add(Usage(prompt_tokens=2, completion_tokens=3))
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 8
    assert usage.total_tokens == 20


def test_cost_estimation():
    from medagent.llm import LLMClient

    client = LLMClient(
        base_url="https://example.invalid", model="m", price_input_per_m=1.0, price_output_per_m=2.0
    )
    body = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1000000, "completion_tokens": 1000000},
    }
    result = client._parse(body)
    assert result.text == "hi"
    assert result.usage.total_tokens == 2000000
    assert result.cost_usd == pytest.approx(3.0)


def test_parse_accepts_content_blocks():
    from medagent.llm import LLMClient

    client = LLMClient(base_url="https://example.invalid", model="m")
    body = {
        "choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    assert client._parse(body).text == "ab"


def test_llm_result_dataclass():
    result = LLMResult(text="x")
    assert result.cost_usd == 0.0
    assert result.usage.total_tokens == 0