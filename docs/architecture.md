# Architecture and design notes

This document records why the agent is built the way it is, and what the
evaluation does and does not show. It is also the interview cheat-sheet:
every section maps to a concrete code path.

## 1. Goals and non-goals

**Goals**

- Answer clinical/evidence questions with citations to real, retrievable sources.
- Make every factual claim auditable: claim -> evidence id -> source URL.
- Be cheap enough to run often (single-digit cents per question on DeepSeek).
- Fail open: one broken tool/image never kills a research run.

**Non-goals**

- Clinical decision support (this is a research tool, not medical advice).
- Beating published benchmarks (the harness reports real behaviour, not SOTA).
- Multi-user production hardening (the HTTP layer is a demo, not a service SLA).

## 2. The loop

`EvidenceAgent.answer()` runs four stages:

1. **Plan** (`_plan`): one LLM call decomposes the question into at most
   `agent.max_sub_questions` sub-questions with JSON output. Sub-questions
   keep the context small and make the evidence board interpretable.
2. **Act** (`_research_sub_question`): for each sub-question, up to
   `agent.max_steps_per_subq` steps. Each step is one JSON decision
   (`thought`, `tool`, `args`). The executor prompt carries the tool schemas,
   the latest 10 evidence previews and the last 6 actions, so the model can
   see what it already knows instead of searching again.
3. **Write** (`_write`): one call produces the cited markdown and a claims
   list where every claim carries evidence ids. The writer never sees the
   trajectory, only the evidence, which keeps the answer anchored.
4. **Verify** (`_verify`): a separate judge call labels each claim
   `supported` / `partial` / `unsupported`. The verifier is a different
   prompt from the writer on purpose: evaluation must not be absorbed by the
   generator.

A global `max_llm_calls` budget (default 30) bounds cost; when exhausted the
agent stops acting and writes from what it has.

## 3. Tools and evidence

Every tool returns `ToolResult(observation, evidence)`: the observation is
the human-readable string the LLM reasons over, the evidence list is what
the system can cite. Evidence ids are stable and self-describing:

| Prefix | Source | Example |
| --- | --- | --- |
| `PMID...` | PubMed abstract | `PMID31535829` |
| `PMC...` | PMC open-access full text | `PMC11839060` |
| `KB:...` | local BM25 knowledge base chunk | `KB:PMC11450654.md#3` |
| `FIG:...` | vision-model answer about a figure | `FIG:...` |

Deduplication happens at insertion (`evidence_id` is the key), so repeated
searches cannot inflate the citation list.

## 4. Figures

PubMed Central full texts expose figure captions and image URLs (resolved
from the article HTML to the current CDN blob paths). The vision tool
downloads the image, sends it to an OpenAI-compatible VLM and records the
answer as evidence. Questions like "what value does the chart reach at
month 18" are answerable even when the caption is silent, which is exactly
where text-only agents lose information.

## 5. Evaluation protocol

`data/eval/questions.jsonl` holds questions with reference key facts.
For each question the harness records:

- **claim grounding rate**: supported claims / verified claims;
- **citation precision**: judge-scored relevance of each cited source;
- **key-fact coverage** and **correctness (1-5)** from a coverage judge;
- cost (USD), tokens, wall time, evidence count.

Threats to validity we accept and describe:

- Judge bias: both verifier and coverage judge are LLMs. The harness
  reports raw answers next to scores so a human can audit them.
- Tuning leak: questions were written while developing the agent; the
  protocol fixes the question file and the corpus snapshot per run.
- PubMed is English-dominant; non-English questions are out of scope.

## 6. Reproducibility and cost

- Config is a single YAML file; secrets live in environment variables.
- The corpus is a frozen directory (`data/corpus`), built by
  `scripts/build_corpus.py` from the E-utilities API.
- Results are written to `runs/<name>/report.md` with the exact command line
  used to produce them.
- Typical budget: one question ≈ 5-9 LLM calls ≈ 30-70 seconds ≈
  $0.01-0.03 on DeepSeek pricing (measured; see runs/eval).