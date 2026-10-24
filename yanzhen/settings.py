from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".artifacts"


def initialize() -> None:
    for folder in (ARTIFACTS, ROOT / ".tmp", ROOT / ".cache" / "browsers"):
        folder.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".cache" / "browsers"))
    os.environ.setdefault("TEMP", str(ROOT / ".tmp"))
    os.environ.setdefault("TMP", str(ROOT / ".tmp"))
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().startswith("YZ_"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def model_config() -> dict:
    return {
        "enabled": os.getenv("YZ_ENABLE_MODEL", "0") == "1",
        "base_url": os.getenv("YZ_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
        "model": os.getenv("YZ_LLM_MODEL", "Qwen3-Coder-30B-A3B-Instruct"),
        "key": os.getenv("YZ_LLM_API_KEY", ""),
        "allow_no_key": os.getenv("YZ_LLM_ALLOW_NO_KEY", "0") == "1",
    }
