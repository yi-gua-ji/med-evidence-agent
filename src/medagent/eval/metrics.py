"""Aggregation metrics for the evaluation report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvalRow:
    """Evaluation outcome for one question."""

    question_id: str
    question: str
    answer_markdown: str = ""
    claims_total: int = 0
    claims_supported: int = 0
    grounding_rate: float = 0.0
    citation_precision: float | None = None
    coverage: float | None = None
    correctness: int | None = None
    unsupported_claims: int = 0
    evidence_count: int = 0
    sub_questions: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    cost_usd: float = 0.0
    total_tokens: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate(rows: list[EvalRow]) -> dict[str, Any]:
    """Compute aggregate metrics across evaluated questions."""
    n = len(rows)
    if not n:
        return {"questions": 0}

    def mean(values: list[float]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 4) if clean else None

    return {
        "questions": n,
        "avg_grounding_rate": mean([row.grounding_rate for row in rows]),
        "avg_citation_precision": mean([row.citation_precision for row in rows]),
        "avg_coverage": mean([row.coverage for row in rows]),
        "avg_correctness": mean([row.correctness for row in rows]),
        "total_unsupported_claims": sum(row.unsupported_claims for row in rows),
        "avg_evidence": round(sum(row.evidence_count for row in rows) / n, 2),
        "avg_latency_s": mean([row.latency_s for row in rows]),
        "total_cost_usd": round(sum(row.cost_usd for row in rows), 6),
        "avg_cost_usd": round(sum(row.cost_usd for row in rows) / n, 6),
        "total_tokens": sum(row.total_tokens for row in rows),
        "errors": sum(len(row.errors) for row in rows),
    }


def to_markdown_table(summary: dict[str, Any]) -> str:
    """Render the aggregate summary as a Markdown table."""
    rows = [
        ("Questions", summary.get("questions")),
        ("Avg claim grounding rate", summary.get("avg_grounding_rate")),
        ("Avg citation precision", summary.get("avg_citation_precision")),
        ("Avg key-fact coverage", summary.get("avg_coverage")),
        ("Avg correctness (1-5)", summary.get("avg_correctness")),
        ("Total unsupported claims", summary.get("total_unsupported_claims")),
        ("Avg evidence items", summary.get("avg_evidence")),
        ("Avg latency (s)", summary.get("avg_latency_s")),
        ("Avg cost (USD)", summary.get("avg_cost_usd")),
        ("Total tokens", summary.get("total_tokens")),
    ]
    lines = ["| Metric | Value |", "| --- | --- |"]
    lines.extend(f"| {name} | {value} |" for name, value in rows)
    return "\n".join(lines)