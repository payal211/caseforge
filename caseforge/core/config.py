import os
from pathlib import Path

DATA_DIR = Path(os.getenv("CASEFORGE_DATA", "./data")).resolve()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
LLM_MODE = os.getenv("LLM_MODE", "auto")  # auto | mock
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))

# Assumptions used only for the productivity metric. Replace with measured numbers.
REVIEW_MINUTES = 3  # human approval time per case
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")  # keep the model in memory during a demo
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
