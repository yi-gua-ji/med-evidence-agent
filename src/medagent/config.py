"""Configuration loading for the Med Evidence Agent.

Configuration lives in YAML (config/default.yaml by default). Secrets are
resolved from environment variables named in the api_key_env fields, so
nothing sensitive is stored in the repository. A custom config path may be
given via the MEA_CONFIG environment variable or the CLI --config flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 2500
    timeout: float = 120.0
    price_input_per_m: float = 0.27
    price_output_per_m: float = 1.10

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


@dataclass
class VisionConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080/v1"
    api_key_env: str = "VISION_API_KEY"
    model: str = "qwen2.5-vl-3b"
    timeout: float = 120.0
    max_image_bytes: int = 8000000

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


@dataclass
class PubMedConfig:
    tool: str = "med-evidence-agent"
    email: str = "med-evidence-agent@example.com"
    api_key_env: str = "NCBI_API_KEY"
    rate_limit_per_sec: float = 2.5
    default_retmax: int = 8

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


@dataclass
class AgentConfig:
    max_sub_questions: int = 5
    max_steps_per_subq: int = 4
    max_evidence_chars: int = 4500
    max_claims: int = 12


@dataclass
class KBConfig:
    corpus_dir: str = "data/corpus"
    top_k: int = 6


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    pubmed: PubMedConfig = field(default_factory=PubMedConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    kb: KBConfig = field(default_factory=KBConfig)
    root_dir: Path = field(default_factory=lambda: Path.cwd())


def _build(cls, data: dict[str, Any]):
    known = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in (data or {}).items() if k in known})


def load_config(path: str | None = None, overrides: dict[str, Any] | None = None) -> Config:
    """Load YAML config, merge overrides, and resolve paths relative to cwd."""
    config_path = path or os.environ.get("MEA_CONFIG") or "config/default.yaml"
    p = Path(config_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    raw: dict[str, Any] = {}
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    cfg = Config(
        llm=_build(LLMConfig, raw.get("llm")),
        vision=_build(VisionConfig, raw.get("vision")),
        pubmed=_build(PubMedConfig, raw.get("pubmed")),
        agent=_build(AgentConfig, raw.get("agent")),
        kb=_build(KBConfig, raw.get("kb")),
        root_dir=Path.cwd(),
    )
    corpus = Path(cfg.kb.corpus_dir)
    cfg.kb.corpus_dir = str(corpus if corpus.is_absolute() else Path.cwd() / corpus)
    return cfg


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out