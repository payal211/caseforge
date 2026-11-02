import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from caseforge import doctor
from caseforge.core import config

GOOD = "Transaction TXN-9001 scored 100/100 on device and velocity signals. A human must approve the recommended block and refund."


def fake_ollama(models, reply):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self): self._send({"models": [{"name": m} for m in models]})
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self._send({"response": reply})
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def live(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LLM_MODE", "auto")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")
    servers = []

    def start(models, reply):
        s = fake_ollama(models, reply)
        servers.append(s)
        monkeypatch.setattr(config, "OLLAMA_URL", f"http://127.0.0.1:{s.server_port}")
    yield start
    for s in servers:
        s.shutdown()


def test_environment_and_packs_pass(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "mock")
    assert not [r for r in doctor.check_environment() + doctor.check_packs() if r.level == "FAIL"]


def test_mock_mode_is_a_warning_not_a_failure(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "mock")
    assert [r.level for r in doctor.check_ollama()] == ["WARN"]


def test_ollama_down_and_model_missing_have_actionable_hints(live, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://127.0.0.1:9")
    r = doctor.check_ollama()[0]
    assert r.level == "FAIL" and "Start the Ollama app" in r.hint
    live(["mistral:7b"], GOOD)
    r = doctor.check_ollama()[0]
    assert r.level == "FAIL" and "ollama pull llama3.1:8b" in r.hint


def test_good_model_output_passes_and_bad_output_warns(live):
    live(["llama3.1:8b"], GOOD)
    assert [r.level for r in doctor.check_ollama()] == ["PASS", "PASS"]
    live(["llama3.1:8b"], "The refund has been approved and issued.")
    res = doctor.check_ollama()
    assert res[1].level == "WARN" and "rejected" in res[1].name
