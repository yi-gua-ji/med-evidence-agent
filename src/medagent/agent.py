"""The evidence agent: plan, tool-augmented research, cited answer, verification."""

from __future__ import annotations

import logging
import time
from typing import Any

from .config import Config
from .llm import LLMClient, LLMError
from .prompts import (
    EXECUTOR_SYSTEM,
    EXECUTOR_USER,
    PLANNER_SYSTEM,
    PLANNER_USER,
    VERIFIER_SYSTEM,
    VERIFIER_USER,
    WRITER_SYSTEM,
    WRITER_USER,
)
from .tools import Tool
from .types import AgentAnswer, Citation, Claim, Evidence, Usage

logger = logging.getLogger(__name__)


class EvidenceAgent:
    """Evidence-grounded research agent.

    The loop is:
    1. plan     - decompose the question into sub-questions;
    2. act      - for each sub-question pick one tool per step, collecting evidence;
    3. write    - compose a cited answer plus the claims it makes;
    4. verify   - check every claim against its cited evidence.

    Every LLM call is accounted (tokens, USD cost, latency) and a global call budget
    stops runaway loops.
    """

    def __init__(
        self,
        cfg: Config,
        tools: dict[str, Tool],
        llm: LLMClient | None = None,
    ) -> None:
        self.cfg = cfg
        self.tools = tools
        self.llm = llm or LLMClient(
            base_url=cfg.llm.base_url,
            model=cfg.llm.model,
            api_key=cfg.llm.api_key,
            temperature=cfg.llm.temperature,
            max_tokens=cfg.llm.max_tokens,
            timeout=cfg.llm.timeout,
            price_input_per_m=cfg.llm.price_input_per_m,
            price_output_per_m=cfg.llm.price_output_per_m,
        )
        self.usage = Usage()
        self.cost_usd = 0.0
        self.max_llm_calls = int(getattr(cfg.agent, "max_llm_calls", 30))
        self._calls = 0

    async def answer(self, question: str) -> AgentAnswer:
        """Run the full plan-act-write-verify loop for one question."""
        started = time.time()
        self.usage = Usage()
        self.cost_usd = 0.0
        self._calls = 0
        trajectory: list[dict[str, Any]] = []
        evidence_pool: dict[str, Evidence] = {}

        sub_questions = await self._plan(question)
        trajectory.append({"stage": "plan", "sub_questions": sub_questions})

        for idx, sub_question in enumerate(sub_questions, start=1):
            await self._research_sub_question(
                question, sub_question, idx, len(sub_questions), evidence_pool, trajectory
            )

        answer_markdown, claims = await self._write(question, sub_questions, evidence_pool)
        claims = await self._verify(claims, evidence_pool)

        citation_ids: list[str] = []
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                if evidence_id not in citation_ids:
                    citation_ids.append(evidence_id)
        citations = [
            Citation(
                evidence_id=evidence_id,
                source=evidence_pool[evidence_id].source,
                title=evidence_pool[evidence_id].title,
                url=evidence_pool[evidence_id].url,
                kind=evidence_pool[evidence_id].kind,
            )
            for evidence_id in citation_ids
            if evidence_id in evidence_pool
        ]

        return AgentAnswer(
            question=question,
            answer_markdown=answer_markdown,
            claims=claims,
            citations=citations,
            sub_questions=sub_questions,
            evidence_count=len(evidence_pool),
            usage=self.usage,
            cost_usd=self.cost_usd,
            latency_s=round(time.time() - started, 2),
            trajectory=trajectory,
        )

    # ------------------------------------------------------------------ plan
    async def _plan(self, question: str) -> list[str]:
        data, _ = await self._chat_json(
            [
                {"role": "system", "content": PLANNER_SYSTEM},
                {
                    "role": "user",
                    "content": PLANNER_USER.format(
                        question=question,
                        max_sub_questions=self.cfg.agent.max_sub_questions,
                    ),
                },
            ]
        )
        subs = [str(s).strip() for s in data.get("sub_questions") or [] if str(s).strip()]
        return subs[: self.cfg.agent.max_sub_questions] or [question]

    # ------------------------------------------------------------------ act
    async def _research_sub_question(
        self,
        question: str,
        sub_question: str,
        idx: int,
        total: int,
        evidence_pool: dict[str, Evidence],
        trajectory: list[dict[str, Any]],
    ) -> None:
        max_steps = max(1, int(self.cfg.agent.max_steps_per_subq))
        for step in range(1, max_steps + 1):
            if self._calls >= self.max_llm_calls:
                trajectory.append({"stage": "budget_exhausted", "sub_question": sub_question})
                return
            data, _ = await self._chat_json(
                [
                    {"role": "system", "content": EXECUTOR_SYSTEM},
                    {
                        "role": "user",
                        "content": EXECUTOR_USER.format(
                            question=question,
                            sub_question=sub_question,
                            subq_index=idx,
                            subq_total=total,
                            tools=self._tools_help(),
                            evidence_board=self._evidence_board(evidence_pool),
                            history=self._history_tail(trajectory),
                            step=step,
                            max_steps=max_steps,
                        ),
                    },
                ]
            )
            tool_name = str(data.get("tool") or "").strip()
            args = data.get("args") or {}
            tool_name = self._resolve_tool_name(tool_name)
            if tool_name in ("finish", "done", ""):
                trajectory.append(
                    {
                        "stage": "finish",
                        "sub_question": sub_question,
                        "thought": data.get("thought", ""),
                    }
                )
                return
            tool = self.tools.get(tool_name)
            if tool is None:
                trajectory.append(
                    {"stage": "act", "sub_question": sub_question, "error": f"unknown tool {tool_name}"}
                )
                continue
            observation = ""
            new_ids: list[str] = []
            try:
                result = await tool.run(args)
                observation = result.observation
                for item in result.evidence:
                    if item.evidence_id not in evidence_pool:
                        evidence_pool[item.evidence_id] = item
                        new_ids.append(item.evidence_id)
            except Exception as exc:  # noqa: BLE001 - tools fail open
                observation = f"tool {tool_name} failed: {exc}"
                logger.warning("tool %s failed: %s", tool_name, exc)
            trajectory.append(
                {
                    "stage": "act",
                    "sub_question": sub_question,
                    "tool": tool_name,
                    "args": args,
                    "thought": data.get("thought", ""),
                    "new_evidence": new_ids,
                    "observation": observation[:1200],
                }
            )

    # ------------------------------------------------------------------ write
    async def _write(
        self,
        question: str,
        sub_questions: list[str],
        evidence_pool: dict[str, Evidence],
    ) -> tuple[str, list[Claim]]:
        if not evidence_pool:
            return (
                "The available evidence was insufficient to answer this question.",
                [],
            )
        data, _ = await self._chat_json(
            [
                {"role": "system", "content": WRITER_SYSTEM},
                {
                    "role": "user",
                    "content": WRITER_USER.format(
                        question=question,
                        sub_questions="; ".join(sub_questions),
                        evidence=self._evidence_block(evidence_pool),
                        max_claims=self.cfg.agent.max_claims,
                    ),
                },
            ],
            max_tokens=max(self.cfg.llm.max_tokens, 2600),
        )
        answer = str(data.get("answer_markdown") or "").strip()
        claims: list[Claim] = []
        for i, raw in enumerate(data.get("claims") or [], start=1):
            text = str((raw or {}).get("text") or "").strip()
            if not text:
                continue
            evidence_ids = [str(x).strip() for x in (raw or {}).get("evidence_ids") or []]
            claims.append(
                Claim(claim_id=f"c{i}", text=text, evidence_ids=[x for x in evidence_ids if x])
            )
        return answer, claims[: self.cfg.agent.max_claims]

    # ------------------------------------------------------------------ verify
    async def _verify(
        self, claims: list[Claim], evidence_pool: dict[str, Evidence]
    ) -> list[Claim]:
        if not claims:
            return claims
        claims_block = "\n".join(
            f"- {c.claim_id}: {c.text} (cites: {', '.join(c.evidence_ids)})" for c in claims
        )
        excerpts: list[str] = []
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                evidence = evidence_pool.get(evidence_id)
                if evidence is not None:
                    excerpts.append(f"[{evidence_id}] " + evidence.text[:700])
        data, _ = await self._chat_json(
            [
                {"role": "system", "content": VERIFIER_SYSTEM},
                {
                    "role": "user",
                    "content": VERIFIER_USER.format(
                        claims=claims_block,
                        evidence="\n\n".join(excerpts[:12]) or "(no excerpts)",
                    ),
                },
            ]
        )
        statuses = {
            str(item.get("claim_id")): str(item.get("status"))
            for item in data.get("results") or []
            if isinstance(item, dict)
        }
        for claim in claims:
            status = statuses.get(claim.claim_id, "unverified")
            if status not in ("supported", "partial", "unsupported"):
                status = "unverified"
            claim.support = status  # type: ignore[assignment]
        return claims

    # ------------------------------------------------------------------ helpers
    async def _chat_json(
        self, messages: list[dict[str, Any]], *, max_tokens: int | None = None
    ) -> tuple[dict[str, Any], Any]:
        self._calls += 1
        result = await self.llm.chat(messages, max_tokens=max_tokens)
        self.usage.add(result.usage)
        self.cost_usd += result.cost_usd
        from .llm import extract_json

        try:
            data = extract_json(result.text)
        except LLMError as exc:
            logger.warning("non-JSON model output: %s", exc)
            data = {}
        return data, result

    def _tools_help(self) -> str:
        return "\n".join(tool.describe() for tool in self.tools.values())

    def _evidence_board(self, pool: dict[str, Evidence], limit: int = 10) -> str:
        if not pool:
            return "(empty)"
        items = list(pool.values())[-limit:]
        return "\n".join(item.preview(320) for item in items)

    def _history_tail(self, trajectory: list[dict[str, Any]], limit: int = 6) -> str:
        acts = [t for t in trajectory if t.get("stage") == "act"]
        if not acts:
            return "(first step)"
        lines = []
        for item in acts[-limit:]:
            lines.append(
                f"step: tool={item.get('tool', '')} args={item.get('args', {})}"
            )
        return "\n".join(lines)

    def _evidence_block(self, pool: dict[str, Evidence], max_total: int | None = None) -> str:
        max_total = max_total or int(self.cfg.agent.max_evidence_chars)
        parts: list[str] = []
        used = 0
        for item in pool.values():
            text = item.text[:900]
            block = f"[{item.evidence_id}] ({item.kind}) {item.title}: {text}"
            if used + len(block) > max_total:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts) or "(empty)"

    @staticmethod
    def _resolve_tool_name(name: str) -> str:
        aliases = {
            "pubmed": "search_pubmed",
            "search": "search_pubmed",
            "kb": "search_kb",
            "vision": "analyze_image",
            "image": "analyze_image",
        }
        return aliases.get(name.lower(), name.lower())