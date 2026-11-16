# Med Evidence Agent

[![tests](https://github.com/yi-gua-ji/med-evidence-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/yi-gua-ji/med-evidence-agent/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/yi-gua-ji/med-evidence-agent)](https://github.com/yi-gua-ji/med-evidence-agent/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/yi-gua-ji/med-evidence-agent)

An evidence-grounded medical research agent: it plans sub-questions, searches
PubMed, reads full texts and figures, writes a cited answer, and then verifies
every claim against the evidence it used. Built to be evaluated, not just demoed.

## Why another research agent?

Generic deep-research agents answer from web search and quietly mix in
parametric memory. In medicine that produces fluent but unverifiable text.
This project makes the evidence chain explicit and measurable:

- **Retrieval is PubMed-first** - titles, abstracts and open-access full texts
  come from NCBI E-utilities, with PMCID resolution and figure metadata.
- **Figures are read, not skipped** - an optional vision tool sends the
  published figure image to a local vision-language model (Qwen2-VL served
  through an OpenAI-compatible endpoint) and returns its values as evidence.
- **Answers carry claim-level support labels** - a separate verification pass
  judges every claim as `supported`, `partial` or `unsupported`, so the
  evaluation can report a real grounding rate instead of a vibe.
- **Every run is accounted** - tokens, USD cost and latency per question.

## How it works

```text
question
   |  plan              (LLM -> 3-5 focused sub-questions)
   v
sub-question loop  ---- act: pick one tool per step (search_pubmed,
   |                          fetch_paper, search_kb, analyze_image, finish)
   |  observe: tool result becomes citable evidence [PMID..]/[PMC..]/[KB..]/[FIG..]
   v
write              (LLM -> cited markdown + claims with evidence ids)
   |
   v
verify             (LLM judge -> supported / partial / unsupported per claim)
   |
   v
cited answer + claim support labels + cost/latency accounting
```

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                           # add DEEPSEEK_API_KEY
python scripts/build_corpus.py 2               # optional: seed the local KB from PMC
medagent doctor                                # config + connectivity check
medagent research "Do SGLT2 inhibitors reduce heart failure hospitalization?"
medagent serve                                 # http://127.0.0.1:8000
```

Any OpenAI-compatible text model works (`llm.base_url` / `llm.model`); any
OpenAI-compatible vision server works for `analyze_image`. The default config
targets DeepSeek for text and a local Qwen2-VL server for vision:

```bash
python scripts/vision_server.py --port 8080 --model Qwen/Qwen2-VL-2B-Instruct
```

## Evaluation

The harness (`medagent eval` / `python scripts/run_eval.py`) runs the agent on
`data/eval/questions.jsonl` and scores four things:

| Metric | What it measures |
| --- | --- |
| Claim grounding rate | share of claims judged `supported` by the verifier |
| Citation precision | share of cited sources the judge finds relevant |
| Key-fact coverage | share of reference key facts covered by the answer |
| Cost / latency | USD and seconds per question, plus total tokens |

Results land in `runs/eval/report.md` (summary table + every answer).

### Results (12-question benchmark, DeepSeek text LLM)

Command: `python scripts/run_eval.py --out runs/eval` on 2026-11-16.

| Metric | Value |
| --- | --- |
| Questions | 12 |
| Avg claim grounding rate | 0.64 |
| Avg citation precision | 0.88 |
| Avg key-fact coverage | 0.57 |
| Avg correctness (1-5) | 3.58 |
| Total unsupported claims | 2 |
| Avg evidence items per question | 28.3 |
| Avg latency | 59 s |
| Avg cost | \$0.014 |
| Total tokens | 508,591 |

Reading: the citation layer is the strong part (precision 0.88), the verifier
is deliberately strict (grounding 0.64 - several trial-level numbers were
only in the abstract, so claims about them were correctly flagged as
unsupported), and almost all questions ended within one minute and one cent.

### Figure QA (vision tool)

Command: `python scripts/run_figure_eval.py --enforce-vision` against a local
`Qwen2-VL-2B-Instruct` server (`scripts/vision_server.py`).

| Category | Questions | Vision correct | Caption-only correct |
| --- | --- | --- | --- |
| Chart value reading (18-month endpoint values) | 4 | 0/4 | 0/4 |
| Labels and group counts | 4 | 4/4 | 0/4 |
| Total | 8 | 4/8 | 0/8 |

**Finding (kept explicit on purpose):** the 2B local model reads axes, labels
and group counts reliably, but mis-maps values to group legends on
multi-series charts - for one weight chart it answered 84 kg where the
article text reports 75.2 kg. The harness reports the two categories
separately instead of hiding the failure behind a single accuracy number; the
drop-in fix is a larger checkpoint (Qwen2.5-VL-7B or a hosted VLM) behind the
same OpenAI-compatible endpoint. The control (caption only) is 0/8, so the
visual channel carries information the caption does not.

## Local vision model (optional)

`scripts/vision_server.py` loads `Qwen/Qwen2-VL-2B-Instruct` (or a larger
Qwen2-VL checkpoint) behind the same `/v1/chat/completions` contract the
vision tool already speaks, so no API key is needed. On an 8 GB consumer GPU
the 2B model leaves room for the vision encoder.

## Configuration

See `config/default.yaml`. Secrets are read from environment variables named
in the `*_api_key_env` fields - nothing sensitive lives in the repository.

## Tests

```bash
pytest -q    # offline: no network, no API keys required
```

## Design notes

- **Tools are plain async classes** with a JSON schema used in prompts; the
  agent never receives a typed python object it cannot reason about.
- **Evidence ids are stable and human-readable** (`PMID...`, `PMC...`,
  `KB:doc#n`, `FIG:...`) so citations survive truncation and JSON round-trips.
- **The verifier is a separate LLM call** deliberately outside the agent loop;
  evaluation must not be able to influence what it evaluates.
- **The agent fails open**: a tool error becomes an observation, a missing
  image is skipped, an exhausted step budget still yields an answer.
- **No embeddings by default**: BM25 keeps the KB reproducible and free of
  model downloads; swap in an embedding index behind `search_kb` if needed.

## Limitations

- English-language content and PubMed indexing bias the evidence pool.
- The verifier is an LLM judge: it catches unsupported claims, not all errors.
- Local Qwen2-VL-2B is a demo-grade vision model; larger checkpoints read
  small figure labels better.
- The `data/corpus` directory holds open-access PubMed Central full texts
  downloaded with `scripts/build_corpus.py`; each article stays under its
  original PMC open-access license.

## License

MIT