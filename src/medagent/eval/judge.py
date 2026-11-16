"""LLM-as-judge helpers used by the evaluation harness.

Judging is separated from the agent so evaluation can never be silently
absorbed into the answer loop: the judge receives only the question, the
generated answer and the reference material, never the agent trajectory.
"""

from __future__ import annotations

import json
from typing import Any

from ..llm import LLMClient, extract_json

CITATION_JUDGE_SYSTEM = """You judge whether the sources cited by a medical research answer
are relevant to the question. For each cited source, decide if it provides meaningful
evidence for answering the question. Answer independently for each source. Return strict
JSON only."""

CITATION_JUDGE_USER = """Question: {question}

Cited sources:
{citations}

Return JSON: {{"results": [{{"evidence_id": "...", "relevant": true, "reason": "..."}}]}}"""

COVERAGE_JUDGE_SYSTEM = """You grade a medical research answer against a checklist of key
facts. A fact counts as covered when the answer states it (paraphrase is fine) and does
not contradict it. Do not reward unsupported extrapolation. Return strict JSON only."""

COVERAGE_JUDGE_USER = """Question: {question}

Key facts:
{key_facts}

Candidate answer:
{answer}

Return JSON: {{"covered": [1, 3], "coverage": 0.5, "correctness": 4, "unsupported_claims": 1, "notes": "..."}}
(covered: 1-based indexes of key facts the answer covers; coverage in [0,1]; correctness:
1-5 overall accuracy of the answer against the facts; unsupported_claims: count of
significant statements not backed by the key facts or common knowledge.)"""


class Judge:
    """Thin wrapper that runs judge prompts and parses their JSON."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def citation_relevance(self, question: str, citations: list[dict[str, Any]]) -> dict[str, bool]:
        """Return relevance flags per cited source."""
        if not citations:
            return {}
        lines = [
            f"- {item.get('evidence_id')}: {item.get('title', '')} | {str(item.get('snippet', ''))[:400]}"
            for item in citations
        ]
        messages = [
            {"role": "system", "content": CITATION_JUDGE_SYSTEM},
            {
                "role": "user",
                "content": CITATION_JUDGE_USER.format(
                    question=question, citations="\n".join(lines)
                ),
            },
        ]
        result = await self.llm.chat(messages, max_tokens=800)
        try:
            data = extract_json(result.text)
        except Exception:  # noqa: BLE001
            return {}
        flags: dict[str, bool] = {}
        for item in data.get("results") or []:
            if isinstance(item, dict) and item.get("evidence_id"):
                flags[str(item["evidence_id"])] = bool(item.get("relevant", False))
        return flags

    async def coverage(self, question: str, key_facts: list[str], answer: str) -> dict[str, Any]:
        """Score an answer against a checklist of key facts."""
        if not key_facts:
            return {"coverage": None, "correctness": None, "covered": []}
        fact_lines = "\n".join(f"{i}. {fact}" for i, fact in enumerate(key_facts, start=1))
        messages = [
            {"role": "system", "content": COVERAGE_JUDGE_SYSTEM},
            {
                "role": "user",
                "content": COVERAGE_JUDGE_USER.format(
                    question=question,
                    key_facts=fact_lines,
                    answer=answer[:6000],
                ),
            },
        ]
        result = await self.llm.chat(messages, max_tokens=600)
        try:
            data = extract_json(result.text)
        except Exception:  # noqa: BLE001
            return {"coverage": None, "correctness": None, "covered": []}
        covered = data.get("covered") or []
        return {
            "coverage": float(data.get("coverage")) if data.get("coverage") is not None else None,
            "correctness": int(data.get("correctness")) if data.get("correctness") is not None else None,
            "covered": covered,
            "unsupported_claims": int(data.get("unsupported_claims") or 0),
            "notes": str(data.get("notes") or ""),
        }