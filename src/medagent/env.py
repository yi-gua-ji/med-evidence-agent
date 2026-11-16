"""Minimal .env loader (no extra dependency)."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (setdefault)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip(chr(34)).strip(chr(39))
        if key:
            os.environ.setdefault(key, value)