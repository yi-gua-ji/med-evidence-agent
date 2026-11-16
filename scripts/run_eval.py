"""Convenience wrapper around the evaluation harness."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.config import load_config  # noqa: E402
from medagent.env import load_env_file  # noqa: E402
from medagent.eval.run import evaluate, load_questions  # noqa: E402


async def main(args: argparse.Namespace) -> None:
    load_env_file()
    cfg = load_config()
    questions = load_questions(args.questions)
    rows, summary = await evaluate(
        cfg, questions, limit=args.limit, out_dir=args.out, judge_answers=not args.no_judge
    )
    print(f"evaluated {len(rows)} questions -> {args.out}")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(Path(__file__).resolve().parents[1] / "data" / "eval" / "questions.jsonl"))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "runs" / "eval"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-judge", action="store_true")
    asyncio.run(main(parser.parse_args()))