"""Agent loop tests with a scripted LLM and fake tools."""

from __future__ import annotations

import pytest

from medagent.agent import EvidenceAgent
from medagent.config import load_config
from medagent.tools.base import Tool, ToolResult
from medagent.types import Evidence, LLMResult, Usage


class FakeLLM:
    """Returns scripted chat responses in order."""

    def __init__(self, responses: list[str], usage: Usage | None = None) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.usage = usage or Usage(prompt_tokens=10, completion_tokens=5)

    async def chat(self, messages, max_tokens=None, temperature=None):
        self.calls += 1
        if not self.responses:
            raise AssertionError("scripted responses exhausted")
        return LLMResult(text=self.responses.pop(0), usage=self.usage, cost_usd=0.0001)


class FakeTool(Tool):
    name = "fake_tool"
    description = "fake"
    args_schema = {"type": "object"}

    def __init__(self, results: list[ToolResult]) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    async def run(self, args):
        self.calls.append(args)
        return self.results.pop(0)


def make_agent(monkeypatch, responses, tools):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = load_config()
    return EvidenceAgent(cfg, tools, llm=FakeLLM(responses))


def evidence(eid: str = "PMID1", text: str = "Empagliflozin reduced hospitalization.") -> Evidence:
    return Evidence(evidence_id=eid, kind="abstract", source=eid, title="trial", text=text)


@pytest.mark.asyncio
async def test_full_loop_produces_cited_answer(monkeypatch):
    tool = FakeTool([ToolResult(observation="result", evidence=[evidence()])])
    responses = [
        '{"sub_questions": ["does empagliflozin reduce hospitalization?"], "rationale": "x"}',
        '{"thought": "search", "tool": "fake_tool", "args": {"query": "empagliflozin"}}',
        '{"thought": "enough", "tool": "finish"}',
        '{"answer_markdown": "Empagliflozin reduced hospitalization [PMID1].", "claims": [{"text": "Empagliflozin reduced hospitalization.", "evidence_ids": ["PMID1"]}]}',
        '{"results": [{"claim_id": "c1", "status": "supported", "reason": "ok"}]}',
    ]
    agent = make_agent(monkeypatch, responses, {"fake_tool": tool})
    answer = await agent.answer("Does empagliflozin reduce hospitalization?")

    assert tool.calls == [{"query": "empagliflozin"}]
    assert answer.sub_questions == ["does empagliflozin reduce hospitalization?"]
    assert "PMID1" in answer.answer_markdown
    assert len(answer.claims) == 1
    assert answer.claims[0].support == "supported"
    assert answer.grounding_rate() == 1.0
    assert answer.citations[0].evidence_id == "PMID1"
    assert answer.evidence_count == 1
    assert answer.usage.prompt_tokens == 50  # five calls x 10


@pytest.mark.asyncio
async def test_unknown_tool_is_skipped(monkeypatch):
    tool = FakeTool([ToolResult(observation="ok", evidence=[evidence()])])
    responses = [
        '{"sub_questions": ["q1"]}',
        '{"thought": "x", "tool": "nope", "args": {}}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "done", "tool": "finish"}',
        '{"answer_markdown": "a [PMID1]", "claims": [{"text": "a", "evidence_ids": ["PMID1"]}]}',
        '{"results": [{"claim_id": "c1", "status": "partial"}]}',
    ]
    agent = make_agent(monkeypatch, responses, {"fake_tool": tool})
    answer = await agent.answer("q")
    assert answer.claims[0].support == "partial"
    assert answer.grounding_rate() == 0.0


@pytest.mark.asyncio
async def test_tool_failure_is_contained(monkeypatch):
    class FailingTool(Tool):
        name = "bad_tool"
        description = "fails"
        args_schema = {"type": "object"}

        async def run(self, args):
            raise RuntimeError("boom")

    responses = [
        '{"sub_questions": ["q1"]}',
        '{"thought": "x", "tool": "bad_tool", "args": {}}',
        '{"thought": "done", "tool": "finish"}',
        '{"answer_markdown": "no evidence", "claims": []}',
    ]
    agent = make_agent(monkeypatch, responses, {"bad_tool": FailingTool()})
    answer = await agent.answer("q")
    assert "insufficient" in answer.answer_markdown.lower()
    assert answer.claims == []


@pytest.mark.asyncio
async def test_duplicate_evidence_is_merged(monkeypatch):
    tool = FakeTool(
        [
            ToolResult(observation="1", evidence=[evidence("PMID9")]),
            ToolResult(observation="2", evidence=[evidence("PMID9")]),
        ]
    )
    responses = [
        '{"sub_questions": ["q1"]}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "done", "tool": "finish"}',
        '{"answer_markdown": "a [PMID9]", "claims": [{"text": "a", "evidence_ids": ["PMID9"]}]}',
        '{"results": [{"claim_id": "c1", "status": "supported"}]}',
    ]
    agent = make_agent(monkeypatch, responses, {"fake_tool": tool})
    answer = await agent.answer("q")
    assert answer.evidence_count == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_the_loop(monkeypatch):
    tool = FakeTool([ToolResult(observation="x", evidence=[])])
    responses = [
        '{"sub_questions": ["q1", "q2", "q3"]}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"thought": "x", "tool": "fake_tool", "args": {}}',
        '{"answer_markdown": "insufficient", "claims": []}',
    ]
    agent = make_agent(monkeypatch, responses, {"fake_tool": tool})
    agent.max_llm_calls = 3
    answer = await agent.answer("q")
    assert "insufficient" in answer.answer_markdown.lower()
    assert any(item.get("stage") == "budget_exhausted" for item in answer.trajectory)