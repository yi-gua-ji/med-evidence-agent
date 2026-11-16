"""OpenAI-compatible local vision server backed by Qwen2-VL.

Runs the same chat-completions contract the VisionTool expects, so the agent
can use a local GPU instead of a paid API. Start with:

    python scripts/vision_server.py --port 8080 --model Qwen/Qwen2-VL-2B-Instruct

Then set vision.enabled=true (and keep vision.base_url at http://127.0.0.1:8080/v1).
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.env import load_env_file  # noqa: E402

import torch  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from PIL import Image  # noqa: E402
from qwen_vl_utils import process_vision_info  # noqa: E402
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration  # noqa: E402

MODEL_ID = os.environ.get("VLM_MODEL", "Qwen/Qwen2-VL-2B-Instruct")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

_processor = None
_model = None


def load() -> None:
    global _processor, _model
    if _model is not None:
        return
    _processor = AutoProcessor.from_pretrained(MODEL_ID)
    _model = Qwen2VLForConditionalGeneration.from_pretrained(
        MODEL_ID, torch_dtype=DTYPE, device_map=DEVICE, low_cpu_mem_usage=True
    )
    _model.eval()


def decode_data_uri(uri: str) -> Image.Image:
    header, _, payload = uri.partition(",")
    if not header.startswith("data:"):
        raise ValueError("only data URIs are supported by this local server")
    return Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGB")


app = FastAPI(title="Qwen2-VL vision server")


@app.on_event("startup")
async def _startup() -> None:
    load_env_file()
    load()


@app.get("/v1/models")
async def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict) -> dict:
    hf_messages = []
    max_tokens = int(payload.get("max_tokens") or 512)
    for message in payload.get("messages") or []:
        content = message.get("content")
        parts = []
        if isinstance(content, str):
            parts.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    parts.append({"type": "text", "text": block.get("text", "")})
                elif block.get("type") == "image_url":
                    image_url = (block.get("image_url") or {}).get("url", "")
                    parts.append({"type": "image", "image": decode_data_uri(image_url)})
        hf_messages.append({"role": message.get("role", "user"), "content": parts})

    text = _processor.apply_chat_template(hf_messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(hf_messages)
    inputs = _processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt")
    if DEVICE == "cuda":
        inputs = inputs.to(DEVICE)

    started = time.time()
    with torch.no_grad():
        output_ids = _model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
    generated = output_ids[:, inputs.input_ids.shape[1]:]
    answer = _processor.batch_decode(generated, skip_special_tokens=True)[0].strip()

    return {
        "id": f"chatcmpl-{int(started)}",
        "object": "chat.completion",
        "created": int(started),
        "model": MODEL_ID,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": int(inputs.input_ids.shape[1]),
            "completion_tokens": int(generated.shape[1]),
            "total_tokens": int(inputs.input_ids.shape[1] + generated.shape[1]),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", default=MODEL_ID)
    args = parser.parse_args()
    MODEL_ID = args.model
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)