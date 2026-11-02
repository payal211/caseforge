from typing import Optional

import httpx

from . import config


class LLM:
    """Thin Ollama client. Returns None on any failure so callers can fall back
    to deterministic text. The platform never depends on the LLM being up."""

    def generate(self, system: str, prompt: str) -> Optional[str]:
        if config.LLM_MODE == "mock":
            return None
        try:
            r = httpx.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                    "options": {"temperature": 0.2, "num_predict": config.LLM_MAX_TOKENS},
                },
                timeout=config.LLM_TIMEOUT,
            )
            r.raise_for_status()
            text = (r.json().get("response") or "").strip()
            return text or None
        except Exception:
            return None
