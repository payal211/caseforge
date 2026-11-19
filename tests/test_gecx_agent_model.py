import pytest

pytest.importorskip("google.adk")
pytest.importorskip("litellm")

from gecx.caseforge_dispute_agent.agent import _model
from gecx.caseforge_dispute_agent.offline_llm import ScriptedGecxLlm


def test_auto_provider_keeps_scripted_offline_model_without_credentials(monkeypatch):
    monkeypatch.setenv("GECX_PROVIDER", "auto")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    assert isinstance(_model(), ScriptedGecxLlm)


def test_ollama_provider_uses_configured_model_and_url(monkeypatch):
    monkeypatch.setenv("GECX_PROVIDER", "ollama")
    monkeypatch.setenv("GECX_MODEL", "gemma3:4b")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")

    model = _model()

    assert model.model == "ollama_chat/gemma3:4b"
