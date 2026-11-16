"""BM25 retrieval over a local literature knowledge base.

The knowledge base is a directory of pre-downloaded PMC articles or notes
(Markdown, plain text or JSONL). Retrieval is deliberately lightweight: no
embedding model is required, so the project runs fully offline and remains
cheap to extend. Every chunk is exposed as citable evidence.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..types import Evidence
from .base import Tool, ToolResult

STOPWORDS = set(
    "a an and are as at be by for from has have if in into is it its of on or the their then these they this to was were will with without we our can may might does did do not no than more less also such using".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords or one-character noise."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


@dataclass
class Chunk:
    chunk_id: str
    title: str
    text: str
    source: str


def chunk_document(text: str, title: str, source: str, max_chars: int = 1200) -> list[Chunk]:
    """Split a document into paragraph-merged chunks of around max_chars."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        current = ""
        for word in para.split():
            if len(current) + len(word) + 1 > max_chars and current:
                pieces.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            pieces.append(current)
    chunks: list[Chunk] = []
    buffer = ""
    for piece in pieces:
        if len(buffer) + len(piece) + 2 > max_chars and buffer:
            chunks.append(Chunk(f"{source}#{len(chunks)}", title, buffer, source))
            buffer = ""
        buffer = (buffer + "\n" + piece).strip() if buffer else piece
    if buffer:
        chunks.append(Chunk(f"{source}#{len(chunks)}", title, buffer, source))
    return chunks


class BM25Index:
    """Classic BM25 scorer over in-memory chunks."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.term_freqs = [Counter(tokenize(chunk.text)) for chunk in chunks]
        self.doc_lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avgdl = (sum(self.doc_lengths) / len(self.doc_lengths)) if chunks else 1.0
        doc_freq: Counter[str] = Counter()
        for tf in self.term_freqs:
            for term in tf:
                doc_freq[term] += 1
        n_docs = len(chunks)
        self.idf = {
            term: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return []
        scored: list[tuple[Chunk, float]] = []
        for chunk, tf, dl in zip(self.chunks, self.term_freqs, self.doc_lengths):
            score = 0.0
            for term in query_terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                score += idf * freq * (self.k1 + 1) / denom
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]


def load_corpus(corpus_dir: str | Path) -> list[Chunk]:
    """Load Markdown/plain-text/JSONL documents from a directory."""
    base = Path(corpus_dir)
    chunks: list[Chunk] = []
    if not base.exists():
        return chunks
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".md", ".txt", ".jsonl"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                title = str(record.get("title") or path.stem)
                body = str(record.get("text") or "")
                if body:
                    chunks.extend(chunk_document(body, title, str(path.name)))
            continue
        title = path.stem
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        chunks.extend(chunk_document(text, title, str(path.name)))
    return chunks


class RAGTool(Tool):
    """Search the local literature knowledge base (BM25, no embeddings)."""

    name = "search_kb"
    description = (
        "Search the local literature knowledge base (pre-downloaded PubMed Central "
        "articles). Returns citable chunks with doc titles. Use it for "
        "definitional, background or cross-paper synthesis questions."
    )
    args_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search terms"},
            "k": {"type": "integer", "default": 6},
        },
        "required": ["query"],
    }

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._index: BM25Index | None = None

    def _get_index(self) -> BM25Index:
        if self._index is None:
            chunks = load_corpus(self.cfg.kb.corpus_dir)
            self._index = BM25Index(chunks)
        return self._index

    async def run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        k = int(args.get("k") or self.cfg.kb.top_k)
        if not query:
            return ToolResult(observation="search_kb needs a non-empty query.")
        index = self._get_index()
        hits = index.search(query, k=max(1, min(k, 10)))
        if not hits:
            return ToolResult(observation=f"No knowledge-base hits for: {query}")
        evidence: list[Evidence] = []
        lines: list[str] = []
        for chunk, score in hits:
            evidence_id = f"KB:{chunk.chunk_id}"
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    kind="kb",
                    source=chunk.source,
                    title=chunk.title,
                    text=chunk.text,
                    url="",
                    meta={"score": round(score, 4)},
                )
            )
            lines.append(f"- [{evidence_id}] ({chunk.title}, score={score:.2f}) {chunk.text[:300]}")
        return ToolResult(observation="\n".join(lines), evidence=evidence)