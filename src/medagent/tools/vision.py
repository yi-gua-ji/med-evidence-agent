"""Vision tool: ask a vision-language model about an image (e.g. paper figure).

The endpoint is any OpenAI-compatible server that accepts image_url content
blocks, typically a local llama.cpp server serving Qwen2.5-VL. The tool is
disabled unless vision.enabled is true in the config.
"""

from __future__ import annotations

import base64
import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import Config
from ..llm import LLMClient
from ..types import Evidence
from .base import Tool, ToolResult, ToolUnavailable


class VisionTool(Tool):
    """Answer a question about one image with a VLM."""

    name = "analyze_image"
    description = (
        "Ask the vision model a question about an image, e.g. a figure from a "
        "paper. Provide the image URL shown in the figure evidence and a specific "
        "question (axis labels, reported values, survival rates)."
    )
    args_schema = {
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "http(s) URL of the image"},
            "question": {"type": "string", "description": "what to extract from the image"},
        },
        "required": ["image_url", "question"],
    }

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = LLMClient(
            base_url=cfg.vision.base_url,
            model=cfg.vision.model,
            api_key=cfg.vision.api_key,
            max_tokens=600,
            timeout=cfg.vision.timeout,
        )

    async def run(self, args: dict[str, Any]) -> ToolResult:
        if not self.cfg.vision.enabled:
            raise ToolUnavailable(
                "vision is disabled (set vision.enabled=true and configure an endpoint)"
            )
        image_url = str(args.get("image_url") or "").strip()
        question = str(args.get("question") or "").strip()
        if not image_url or not question:
            return ToolResult(observation="analyze_image needs image_url and question.")
        image_bytes, mime_type = await self._download(image_url)
        data_uri = (
            f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        result = await self.client.chat(messages)
        answer = result.text[:1200]
        evidence = Evidence(
            evidence_id=f"FIG:{abs(hash(image_url)) % 100000}",
            kind="figure",
            source=image_url,
            title=f"VLM answer: {question[:80]}",
            text=answer,
            url=image_url,
            meta={"question": question, "image_url": image_url},
        )
        return ToolResult(
            observation=f"Vision model answer for {image_url}: {answer}", evidence=[evidence]
        )

    async def _download(self, url: str) -> tuple[bytes, str]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ToolUnavailable(f"unsupported image URL: {url}")
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            if address.is_private or address.is_loopback or address.is_link_local:
                raise ToolUnavailable(f"refusing to fetch private address: {host}")
        except ValueError:
            if host == "localhost" or host.endswith(".local"):
                raise ToolUnavailable(f"refusing to fetch private address: {host}")
        timeout = httpx.Timeout(self.cfg.vision.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            if len(response.content) > self.cfg.vision.max_image_bytes:
                raise ToolUnavailable("image larger than max_image_bytes")
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = "image/png"
            return response.content, content_type