"""Minimal OpenAI-compatible async chat client with usage and cost accounting.

The same client serves the text LLM (e.g. DeepSeek) and the vision endpoint
(any OpenAI-compatible server, e.g. llama.cpp serving Qwen2.5-VL), so the
provider can be swapped through configuration alone.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import json_repair

from .types import LLMResult, Usage

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when an LLM request fails after all retries."""


class LLMClient:
    """Async OpenAI-compatible chat-completions client.

    Attributes:
        base_url: Endpoint base URL, e.g. https://api.deepseek.com.
        model: Model name sent with every request.
        price_input_per_m: USD per 1M input tokens (cost reporting only).
        price_output_per_m: USD per 1M output tokens.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2500,
        timeout: float = 120.0,
        price_input_per_m: float = 0.0,
        price_output_per_m: float = 0.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.default_max_tokens = max_tokens
        self.timeout = timeout
        self.price_input_per_m = price_input_per_m
        self.price_output_per_m = price_output_per_m
        self.max_retries = max_retries

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Send one chat request and return the text plus token accounting."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.default_max_tokens if max_tokens is None else max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                if response.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                body = response.json()
                return self._parse(body)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                delay = min(2 ** attempt, 20)
                logger.warning("LLM request failed (attempt %d/%d): %s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> tuple[dict[str, Any], LLMResult]:
        """Chat and parse the reply as JSON (tolerates fences and small damage)."""
        result = await self.chat(messages, max_tokens=max_tokens, temperature=temperature)
        data = extract_json(result.text)
        return data, result

    def _parse(self, body: dict[str, Any]) -> LLMResult:
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("response has no choices")
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        if isinstance(text, list):
            text = "".join(
                block.get("text", "") for block in text if isinstance(block, dict)
            )
        usage_raw = body.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
        )
        cost = (
            usage.prompt_tokens / 1_000_000 * self.price_input_per_m
            + usage.completion_tokens / 1_000_000 * self.price_output_per_m
        )
        return LLMResult(text=text.strip(), usage=usage, cost_usd=cost)


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output, repairing fences and truncation."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    try:
        data = json_repair.loads(cleaned)
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"could not parse JSON from model output: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"expected a JSON object, got {type(data).__name__}")
    return data