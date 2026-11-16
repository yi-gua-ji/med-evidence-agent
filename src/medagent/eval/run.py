"""Run the agent over a question set and produce an evaluation report."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import Config
from ..factory import make_agent, make_judge
from ..types import AgentAnswer
from .metrics import EvalRow, aggregate, to_markdown_table

logger = logging.getLogger(__name__)


def load_questions(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSONL question file."""
    questions: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


async def evaluate(
    cfg: Config,
    questions: list[dict[str, Any]],
    *,
    limit: int | None = None,
    out_dir: str | Path = "runs",
    judge_answers: bool = True,
) -> tuple[list[EvalRow], dict[str, Any]]:
    """Evaluate the agent on a list of questions and write a report.

    Args:
        cfg: Loaded config.
        questions: Rows with question, optional id/topic/key_facts.
        limit: Optional cap on the number of questions.
        out_dir: Directory for results.jsonl and report.md.
        judge_answers: Whether to run the LLM judges (coverage and citations).

    Returns:
        The evaluated rows and the aggregate summary.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected = questions[:limit] if limit else questions
    judge = make_judge(cfg) if judge_answers else None
    rows: list[EvalRow] = []

    for index, item in enumerate(selected, start=1):
        question_id = str(item.get("id") or f"q{index}")
        question = str(item.get("question") or "").strip()
        logger.info("Evaluating %s/%s: %s", index, len(selected), question[:80])
        row = EvalRow(question_id=question_id, question=question)
        try:
            agent = make_agent(cfg)
            answer: AgentAnswer = await agent.answer(question)
        except Exception as exc:  # noqa: BLE001 - keep the harness alive
            logger.exception("agent failed on %s", question_id)
            row.errors.append(f"agent: {exc}")
            rows.append(row)
            continue

        row.answer_markdown = answer.answer_markdown
        row.claims_total = len(answer.claims)
        row.claims_supported = sum(1 for c in answer.claims if c.support == "supported")
        row.grounding_rate = round(answer.grounding_rate(), 4)
        row.evidence_count = answer.evidence_count
        row.sub_questions = list(answer.sub_questions)
        row.latency_s = answer.latency_s
        row.cost_usd = round(answer.cost_usd, 6)
        row.total_tokens = answer.usage.total_tokens
        row.errors.extend(answer.errors)

        if judge is not None and answer.citations:
            citations = [
                {
                    "evidence_id": citation.evidence_id,
                    "title": citation.title,
                    "snippet": "",
                }
                for citation in answer.citations
            ]
            try:
                flags = await judge.citation_relevance(question, citations)
                if flags:
                    row.citation_precision = round(
                        sum(1 for value in flags.values() if value) / len(flags), 4
                    )
            except Exception as exc:  # noqa: BLE001
                row.errors.append(f"judge citations: {exc}")

        key_facts = [str(f) for f in item.get("key_facts") or []]
        if judge is not None and key_facts:
            try:
                coverage = await judge.coverage(question, key_facts, answer.answer_markdown)
                row.coverage = coverage.get("coverage")
                row.correctness = coverage.get("correctness")
                row.unsupported_claims = int(coverage.get("unsupported_claims") or 0)
            except Exception as exc:  # noqa: BLE001
                row.errors.append(f"judge coverage: {exc}")

        rows.append(row)

    summary = aggregate(rows)
    with (out / "results.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    report = render_report(rows, summary)
    (out / "report.md").write_text(report, encoding="utf-8")
    return rows, summary


def render_report(rows: list[EvalRow], summary: dict[str, Any]) -> str:
    """Render a Markdown report of one evaluation run."""
    lines = ["# Evaluation report", "", to_markdown_table(summary), ""]
    lines.append("## Per-question results")
    lines.append("")
    lines.append("| id | grounding | citation P | coverage | correct | unsupported | evidence | latency s | cost USD |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            f"| {row.question_id} | {row.grounding_rate} | {row.citation_precision} | "
            f"{row.coverage} | {row.correctness} | {row.unsupported_claims} | "
            f"{row.evidence_count} | {row.latency_s} | {row.cost_usd} |"
        )
    lines.append("")
    lines.append("## Answers")
    for row in rows:
        lines.append(f"### {row.question_id}")
        lines.append("")
        lines.append(f"**Question:** {row.question}")
        lines.append("")
        lines.append(row.answer_markdown or "(no answer)")
        lines.append("")
        if row.errors:
            lines.append("Errors: " + "; ".join(row.errors))
            lines.append("")
    return "\n".join(lines)