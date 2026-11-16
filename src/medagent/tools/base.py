"""Tool protocol shared by every capability of the agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..types import Evidence


class ToolUnavailable(RuntimeError):
    """Raised when a tool cannot run (not configured, endpoint down...)."""


@dataclass
class ToolResult:
    """Observation returned to the agent plus the evidence it discovered."""

    observation: str
    evidence: list[Evidence] = field(default_factory=list)


class Tool(ABC):
    """A callable capability with a self-description used in prompts."""

    name: str = ""
    description: str = ""
    args_schema: dict[str, Any] = {}

    @abstractmethod
    async def run(self, args: dict[str, Any]) -> ToolResult:
        """Execute the tool with validated arguments."""

    def describe(self) -> str:
        line1 = f"- {self.name}: {self.description}"
        line2 = f"  arguments JSON schema: {self.args_schema}"
        return line1 + "\n" + line2