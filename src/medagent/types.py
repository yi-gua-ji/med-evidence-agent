"""Shared dataclasses for the evidence agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Usage:
    """Token usage of one or more LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResult:
    """Text plus accounting returned by one LLM call."""

    text: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0


@dataclass
class Evidence:
    """A piece of retrieved evidence (literature chunk, figure description...)."""

    evidence_id: str
    kind: Literal["abstract", "fulltext", "kb", "figure"]
    source: str
    title: str = ""
    text: str = ""
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def preview(self, max_chars: int = 600) -> str:
        text = self.text.strip()
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return f"[{self.evidence_id}] ({self.kind}) {self.title or self.source}: {text}"


@dataclass
class Claim:
    """One factual claim of the final answer and the evidence it rests on."""

    claim_id: str
    text: str
    evidence_ids: list[str] = field(default_factory=list)
    support: Literal["supported", "partial", "unsupported", "unverified"] = "unverified"


@dataclass
class Citation:
    """A source cited in the final answer."""

    evidence_id: str
    source: str
    title: str = ""
    url: str = ""
    kind: str = "paper"


@dataclass
class AgentAnswer:
    """The agent final output plus all accounting needed for evaluation."""

    question: str
    answer_markdown: str
    claims: list[Claim] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    sub_questions: list[str] = field(default_factory=list)
    evidence_count: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def grounding_rate(self) -> float:
        verified = [c for c in self.claims if c.support in ("supported", "partial", "unsupported")]
        if not verified:
            return 0.0
        supported = sum(1 for c in verified if c.support == "supported")
        return supported / len(verified)