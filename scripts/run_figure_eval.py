"""Evaluate the vision tool on figure questions with known gold answers."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.config import load_config  # noqa: E402
from medagent.env import load_env_file  # noqa: E402
from medagent.tools.vision import VisionTool  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "eval" / "figure_questions.jsonl"
OUT = Path(__file__).resolve().parents[1] / "runs" / "figure_eval"


def numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


def numeric_match(answer: str, gold: float, tolerance_ratio: float = 0.05) -> bool:
    tolerance = max(abs(gold) * tolerance_ratio, 0.5)
    return any(abs(value - gold) <= tolerance for value in numbers(answer))


def judge_answer(row: dict, answer: str) -> bool:
    gold_value = row.get("gold_value")
    if gold_value is not None:
        return numeric_match(answer, float(gold_value))
    gold_text = str(row.get("gold_answer") or "").lower()
    return bool(gold_text) and gold_text in answer.lower()


async def main(limit: int | None, enforce_vision: bool) -> None:
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    load_env_file()
    cfg = load_config()
    if enforce_vision:
        cfg.vision.enabled = True
    if not cfg.vision.enabled:
        raise SystemExit("vision.enabled is false - start scripts/vision_server.py and enable vision")
    tool = VisionTool(cfg)
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = rows[:limit] if limit else rows
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for row in rows:
        print(f"[{row['id']}] {row['question'][:90]}")
        result = await tool.run({"image_url": row["image_url"], "question": row["question"]})
        answer = result.evidence[0].text if result.evidence else result.observation
        vision_ok = judge_answer(row, answer)
        caption_ok = judge_answer(row, str(row.get("caption", "")))
        results.append(
            {
                "id": row["id"],
                "question": row["question"],
                "gold": row.get("gold_answer"),
                "vision_answer": answer,
                "vision_correct": vision_ok,
                "caption_only_correct": caption_ok,
            }
        )
        print(f"   answer: {answer[:200]}")
        print(f"   vision_correct={vision_ok} caption_correct={caption_ok}")
    n = len(results)
    vision_acc = sum(1 for r in results if r["vision_correct"]) / n if n else 0.0
    caption_acc = sum(1 for r in results if r["caption_only_correct"]) / n if n else 0.0
    summary = {"questions": n, "vision_accuracy": round(vision_acc, 4), "caption_only_accuracy": round(caption_acc, 4)}
    (OUT / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )
    lines = ["# Figure QA evaluation", "", "| id | vision correct | caption-only correct |", "| --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r['id']} | {r['vision_correct']} | {r['caption_only_correct']} |")
    lines.append("")
    lines.append(f"Vision accuracy: {summary['vision_accuracy']}")
    lines.append(f"Caption-only accuracy: {summary['caption_only_accuracy']}")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--enforce-vision", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.enforce_vision))