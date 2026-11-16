"""Tool registry for the evidence agent."""

from __future__ import annotations

from ..config import Config
from .base import Tool, ToolResult, ToolUnavailable
from .pubmed import PubMedTool
from .rag import RAGTool
from .vision import VisionTool

__all__ = ["Tool", "ToolResult", "ToolUnavailable", "build_tools"]


def build_tools(cfg: Config) -> dict[str, Tool]:
    """Instantiate the default tool set for a config."""
    return {
        "search_pubmed": PubMedTool(cfg),
        "fetch_paper": PubMedTool(cfg),
        "search_kb": RAGTool(cfg),
        "analyze_image": VisionTool(cfg),
    }