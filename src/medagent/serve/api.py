"""FastAPI service exposing the evidence agent over HTTP.

Endpoints:
  GET  /healthz  - liveness probe (always cheap)
  POST /research - run the agent for one question and return the cited answer
  GET  /         - a tiny demo page that calls /research
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..config import load_config
from ..env import load_env_file
from ..factory import make_agent
from ..types import AgentAnswer

logger = logging.getLogger(__name__)


class ResearchRequest(BaseModel):
    """Payload for POST /research."""

    question: str = Field(min_length=5, description="medical question to research")
    vision: bool | None = Field(default=None, description="override vision.enabled")


app = FastAPI(title="Med Evidence Agent", version=__version__)


def _answer_payload(answer: AgentAnswer) -> dict[str, Any]:
    return {
        "answer_markdown": answer.answer_markdown,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "text": claim.text,
                "evidence_ids": claim.evidence_ids,
                "support": claim.support,
            }
            for claim in answer.claims
        ],
        "citations": [
            {
                "evidence_id": citation.evidence_id,
                "source": citation.source,
                "title": citation.title,
                "url": citation.url,
                "kind": citation.kind,
            }
            for citation in answer.citations
        ],
        "sub_questions": answer.sub_questions,
        "evidence_count": answer.evidence_count,
        "grounding_rate": round(answer.grounding_rate(), 4),
        "usage": {
            "prompt_tokens": answer.usage.prompt_tokens,
            "completion_tokens": answer.usage.completion_tokens,
            "total_tokens": answer.usage.total_tokens,
            "cost_usd": round(answer.cost_usd, 6),
        },
        "latency_s": answer.latency_s,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


@app.post("/research")
async def research(request: ResearchRequest) -> dict[str, Any]:
    """Run the agent for one question."""
    load_env_file()
    cfg = load_config()
    if request.vision is not None:
        cfg.vision.enabled = bool(request.vision)
    agent = make_agent(cfg)
    answer = await agent.answer(request.question)
    return _answer_payload(answer)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """A minimal demo page for manual testing."""
    return (
        "<html><head><meta charset=\"utf-8\"><title>Med Evidence Agent</title></head>"
        "<body style=\"font-family: sans-serif; max-width: 760px; margin: 40px auto;\">"
        "<h2>Med Evidence Agent</h2>"
        "<p>Evidence-grounded medical research with PubMed citations.</p>"
        "<textarea id=\"q\" rows=\"3\" style=\"width:100%\" placeholder=\"Ask a medical question...\"></textarea>"
        "<button onclick=\"ask()\">Research</button><pre id=\"out\"></pre>"
        "<script>async function ask(){const q=document.getElementById(\"q\").value;"
        "const r=await fetch(\"/research\",{method:\"POST\",headers:{\"Content-Type\":\"application/json\"},"
        "body:JSON.stringify({question:q})});document.getElementById(\"out\").textContent=JSON.stringify(await r.json(),null,2);}</script>"
        "</body></html>"
    )