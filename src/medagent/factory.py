"""Construct the agent, judge and tools from a config."""

from __future__ import annotations

from .agent import EvidenceAgent
from .config import Config
from .eval.judge import Judge
from .llm import LLMClient
from .types import Evidence


def make_llm(cfg: Config) -> LLMClient:
    """Build the text LLM client from config."""
    return LLMClient(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        api_key=cfg.llm.api_key,
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
        timeout=cfg.llm.timeout,
        price_input_per_m=cfg.llm.price_input_per_m,
        price_output_per_m=cfg.llm.price_output_per_m,
    )


def make_judge(cfg: Config) -> Judge:
    """Build a judge that shares the text LLM."""
    return Judge(make_llm(cfg))


def make_agent(cfg: Config, tools: dict | None = None) -> EvidenceAgent:
    """Build the default agent from config."""
    if tools is None:
        from .tools import build_tools

        tools = build_tools(cfg)
    return EvidenceAgent(cfg, tools, llm=make_llm(cfg))