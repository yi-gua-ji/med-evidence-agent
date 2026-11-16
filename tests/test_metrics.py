"""Metrics aggregation tests."""

from __future__ import annotations

from medagent.eval.metrics import EvalRow, aggregate, to_markdown_table


def test_aggregate_empty():
    assert aggregate([]) == {"questions": 0}


def test_aggregate_means():
    rows = [
        EvalRow(question_id="a", question="q1", grounding_rate=1.0, citation_precision=0.5, coverage=0.8, correctness=4, evidence_count=3, latency_s=2.0, cost_usd=0.001, total_tokens=100, unsupported_claims=1),
        EvalRow(question_id="b", question="q2", grounding_rate=0.5, citation_precision=1.0, coverage=0.4, correctness=2, evidence_count=5, latency_s=4.0, cost_usd=0.003, total_tokens=200, unsupported_claims=0),
    ]
    summary = aggregate(rows)
    assert summary["questions"] == 2
    assert summary["avg_grounding_rate"] == 0.75
    assert summary["avg_citation_precision"] == 0.75
    assert summary["avg_coverage"] == 0.6
    assert summary["avg_correctness"] == 3.0
    assert summary["total_unsupported_claims"] == 1
    assert summary["avg_cost_usd"] == 0.002


def test_markdown_table_contains_metrics():
    table = to_markdown_table(aggregate([EvalRow(question_id="a", question="q", grounding_rate=1.0)]))
    assert "Avg claim grounding rate" in table
    assert "| Metric | Value |" in table