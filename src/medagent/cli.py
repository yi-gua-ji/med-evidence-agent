"""Command line interface: research, evaluate, serve, doctor."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .config import load_config
from .env import load_env_file


async def _research(question: str, vision: bool | None, out: str | None) -> None:
    from .factory import make_agent

    cfg = load_config()
    if vision is not None:
        cfg.vision.enabled = bool(vision)
    agent = make_agent(cfg)
    answer = await agent.answer(question)
    payload = {
        "answer_markdown": answer.answer_markdown,
        "claims": [
            {"claim_id": c.claim_id, "text": c.text, "evidence_ids": c.evidence_ids, "support": c.support}
            for c in answer.claims
        ],
        "citations": [{"evidence_id": c.evidence_id, "title": c.title, "url": c.url} for c in answer.citations],
        "sub_questions": answer.sub_questions,
        "evidence_count": answer.evidence_count,
        "grounding_rate": round(answer.grounding_rate(), 4),
        "usage": {"prompt_tokens": answer.usage.prompt_tokens, "completion_tokens": answer.usage.completion_tokens},
        "cost_usd": round(answer.cost_usd, 6),
        "latency_s": answer.latency_s,
    }
    print(answer.answer_markdown)
    print()
    print(json.dumps({k: payload[k] for k in ("grounding_rate", "evidence_count", "cost_usd", "latency_s")}, indent=2))
    print(f"citations: {len(answer.citations)}, claims: {len(answer.claims)}")
    if out:
        from pathlib import Path
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"saved -> {out}")


async def _evaluate(questions: str, out_dir: str, limit: int | None, no_judge: bool) -> None:
    from .eval.run import evaluate, load_questions

    cfg = load_config()
    rows = load_questions(questions)
    _, summary = await evaluate(cfg, rows, limit=limit, out_dir=out_dir, judge_answers=not no_judge)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


async def _doctor() -> int:
    """Check config, secrets and endpoint connectivity."""
    import httpx

    cfg = load_config()
    status: list[tuple[str, str]] = []
    status.append(("llm provider", f"{cfg.llm.model} @ {cfg.llm.base_url}"))
    status.append(("api key set", "yes" if cfg.llm.api_key else "NO (set DEEPSEEK_API_KEY)"))
    status.append(("vision", f"{cfg.vision.model} @ {cfg.vision.base_url} (enabled={cfg.vision.enabled})"))
    corpus = cfg.kb.corpus_dir
    try:
        from pathlib import Path

        files = list(Path(corpus).glob("**/*")) if Path(corpus).exists() else []
        status.append(("kb corpus", f"{len(files)} files in {corpus}"))
    except Exception as exc:  # noqa: BLE001
        status.append(("kb corpus", f"error: {exc}"))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": "heart", "retmax": 1, "retmode": "json"},
            )
        status.append(("ncbi eutils", "ok" if resp.status_code == 200 else f"http {resp.status_code}"))
    except Exception as exc:  # noqa: BLE001
        status.append(("ncbi eutils", f"error: {exc}"))
    width = max(len(name) for name, _ in status)
    for name, value in status:
        print(f"{name.ljust(width)} : {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(prog="medagent", description="Med Evidence Agent")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_research = sub.add_parser("research", help="answer one medical question")
    p_research.add_argument("question")
    p_research.add_argument("--vision", action="store_true", help="enable the vision tool")
    p_research.add_argument("--out", default=None, help="write the JSON result to this path")

    p_eval = sub.add_parser("eval", help="run the evaluation harness")
    p_eval.add_argument("--questions", default="data/eval/questions.jsonl")
    p_eval.add_argument("--out", default="runs/eval")
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--no-judge", action="store_true", help="skip the LLM judges")

    p_serve = sub.add_parser("serve", help="run the HTTP service")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("doctor", help="check configuration and connectivity")

    args = parser.parse_args(argv)
    if args.command == "research":
        asyncio.run(_research(args.question, args.vision or None, args.out))
    elif args.command == "eval":
        asyncio.run(_evaluate(args.questions, args.out, args.limit, args.no_judge))
    elif args.command == "doctor":
        return asyncio.run(_doctor())
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("medagent.serve.api:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())