"""Sandbox tests. A fake container CLI (a Python script) lets these run on Windows, macOS and Linux without
Docker: they verify the exact hardened command, the stdin protocol, timeouts, output caps and fail-closed behaviour.
Real container isolation is checked on a real machine with:  python -m caseforge.harness sandbox-check"""
import json
import os
import sys
import textwrap

import pytest

from caseforge.core import config
from caseforge.core.jev import JevClient
from caseforge.core.orchestrator import Orchestrator
from caseforge.harness import sandbox as sbx
from caseforge.harness.sandbox import BOOTSTRAP, Sandbox, SandboxConfig, SandboxResult, detect_runtime, self_test
from caseforge.harness.tools import build_toolbox
from caseforge.packs import load_packs
from tests.test_harness import INJECT, Script, call, final

config.LLM_MODE = "mock"

FAKE = textwrap.dedent('''
    import json, os, subprocess, sys, time
    a = sys.argv[1:]
    log = os.environ.get("FAKE_LOG")
    def note(**k):
        if log: open(log, "a").write(json.dumps(k) + "\\n")
    mode = os.environ.get("FAKE_MODE", "ok")
    if a[:1] == ["info"]: sys.exit(1 if mode == "down" else 0)
    if a[:2] == ["image", "inspect"]: sys.exit(1 if mode == "noimage" else 0)
    if a[:1] in (["kill"], ["rm"]): note(cleanup=a); sys.exit(0)
    if a[:1] == ["run"]:
        stdin = sys.stdin.buffer.read()
        note(args=a, stdin=stdin.decode())
        if mode == "sleep": time.sleep(60)
        if mode == "big": sys.stdout.write("A" * 50000); sys.exit(0)
        if mode == "fail": sys.stderr.write("boom"); sys.exit(3)
        boot = a[a.index("-c") + 1]
        p = subprocess.run([sys.executable, "-I", "-c", boot], input=stdin, capture_output=True)
        sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); sys.exit(p.returncode)
''')


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_runtime.py"
    script.write_text(FAKE, encoding="utf-8")
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_MODE", "ok")

    def make(**cfg):
        return Sandbox(SandboxConfig(**cfg), runtime_cmd=[sys.executable, str(script)])
    make.log = lambda: [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    return make


def test_command_is_hardened_and_shell_free():
    args = Sandbox(runtime_cmd=["docker"]).build_run_args("n1")
    assert isinstance(args, list) and args[:2] == ["docker", "run"]
    for flag in ("--rm", "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pull=never"):
        assert flag in args
    assert args[args.index("--user") + 1] == "65534:65534"
    assert {"--memory", "--cpus", "--pids-limit"} <= set(args)
    assert args[args.index("--memory-swap") + 1] == args[args.index("--memory") + 1]  # no swap
    assert not {"-v", "--volume", "--mount", "--privileged", "--network=host", "--env", "-e"} & set(args)
    assert args[-1] == BOOTSTRAP and args.index("python:3.12-slim") < args.index("python")  # image after all flags


def test_runtime_detection_order_and_override(monkeypatch):
    monkeypatch.delenv("CASEFORGE_SANDBOX_RUNTIME", raising=False)
    monkeypatch.setattr(sbx.shutil, "which", lambda n: f"/bin/{n}" if n == "podman" else None)
    assert detect_runtime() == ["/bin/podman"]
    monkeypatch.setattr(sbx.shutil, "which", lambda n: f"/bin/{n}" if n in ("docker", "podman") else None)
    assert detect_runtime() == ["/bin/docker"]
    monkeypatch.setattr(sbx.shutil, "which", lambda n: None)
    assert detect_runtime() is None
    monkeypatch.setenv("CASEFORGE_SANDBOX_RUNTIME", "nonexistent-runtime")
    assert detect_runtime() is None
    monkeypatch.setenv("CASEFORGE_SANDBOX_RUNTIME", sys.executable)
    assert detect_runtime() == [sys.executable]


def test_status_explains_each_failure_in_plain_words(fake, monkeypatch):
    monkeypatch.setattr(sbx, "detect_runtime", lambda: None)
    ok, why = Sandbox(enabled=True).status()
    assert not ok and "Docker Desktop" in why and "Colima does not run on Windows" in why
    assert Sandbox(enabled=False).status() == (False, "sandbox is off (set CASEFORGE_SANDBOX=on)")
    monkeypatch.setenv("FAKE_MODE", "down")
    assert "not running" in fake().status(fresh=True)[1]
    monkeypatch.setenv("FAKE_MODE", "noimage")
    assert "sandbox-setup" in fake().status(fresh=True)[1]
    monkeypatch.setenv("FAKE_MODE", "ok")
    assert fake().status(fresh=True)[0] is True


def test_code_and_data_travel_over_stdin_and_the_bootstrap_really_runs_them(fake):
    r = fake().run("print(sum(data['x']) * 2)", {"x": [1, 2, 3]})
    assert r.ok and r.stdout.strip() == "12" and r.exit_code == 0
    entry = fake.log()[0]
    assert "print(sum" not in " ".join(entry["args"])  # model code never appears on the command line
    assert json.loads(entry["stdin"]) == {"code": "print(sum(data['x']) * 2)", "data": {"x": [1, 2, 3]}}


def test_errors_exit_codes_truncation_and_limits(fake, monkeypatch):
    bad = fake().run("raise ValueError('nope')")
    assert not bad.ok and bad.exit_code != 0 and "ValueError" in bad.stderr
    monkeypatch.setenv("FAKE_MODE", "fail")
    assert fake().run("x").exit_code == 3
    monkeypatch.setenv("FAKE_MODE", "big")
    r = fake(max_output=100).run("x")
    assert r.truncated and len(r.stdout) == 100
    assert not fake().run("x" * 600_000).ok


def test_timeout_kills_and_removes_the_container(fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    r = fake(timeout=1, grace=1).run("while True: pass")
    assert r.timed_out and not r.ok and r.seconds < 15
    cleanup = [e["cleanup"][0] for e in fake.log() if "cleanup" in e]
    assert "kill" in cleanup and "rm" in cleanup


def test_disabled_or_missing_runtime_fails_closed():
    r = Sandbox(enabled=False).run("print(1)")
    assert not r.ok and "unavailable" in r.stderr and r.exit_code is None


class FakeSandbox:
    enabled, available = True, True

    def __init__(self, stdout="42\n"):
        self.seen, self.stdout = [], stdout

    def run(self, code, data=None):
        self.seen.append((code, data))
        return SandboxResult(True, 0, stdout=self.stdout)


def test_run_python_tool_exists_only_when_the_sandbox_is_ready():
    pack = load_packs()["bfsi"]
    assert "run_python" in build_toolbox(pack, [], FakeSandbox(), {}).tools
    assert "run_python" not in build_toolbox(pack, [], None, {}).tools
    off = FakeSandbox(); off.enabled = False
    assert "run_python" not in build_toolbox(pack, [], off, {}).tools
    down = FakeSandbox(); down.available = False
    assert "run_python" not in build_toolbox(pack, [], down, {}).tools
    names = build_toolbox(pack, [], FakeSandbox(), {}).tools
    assert not any(k in n for n in names for k in ("approve", "decide", "reject", "override", "refund", "block"))


def test_tool_validates_code_and_redacts_hostile_output():
    tb = build_toolbox(load_packs()["bfsi"], [], FakeSandbox(INJECT), {})
    assert not tb.call("run_python", {"code": ""}).ok and not tb.call("run_python", {"code": "x" * 4001}).ok
    assert not tb.call("run_python", {"code": 5}).ok and not tb.call("run_python", {}).ok
    res = tb.call("run_python", {"code": "print(1)"})
    assert res.ok and INJECT not in res.text and res.flags  # output of model-run code is untrusted data


def test_agent_can_compute_in_the_sandbox_without_changing_the_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    packs, fs = load_packs(), FakeSandbox("total weight 100\n")
    base = Orchestrator(packs, jev=JevClient(enabled=False), agentic=False).investigate("bfsi", "TXN-9001")
    llm = Script([call("run_python", code="print(sum(e['weight'] for e in data['evidence']))"),
                  final(("Evidence weights sum to the full score.", ["T1"]))])
    c = Orchestrator(packs, llm=llm, jev=JevClient(enabled=False), agentic=True, sandbox=fs).investigate("bfsi", "TXN-9001")
    assert c.agent_run["status"] == "completed" and c.agent_run["notes"][0]["evidence"] == ["T1"]
    code, data = fs.seen[0]
    assert {e["signal"] for e in data["evidence"]} >= {"new_device", "shared_device"} and "record" in data
    assert (c.risk_score, c.recommended_action) == (base.risk_score, base.recommended_action)
    assert c.status.value == "pending_approval"


def test_self_test_cannot_pass_without_a_real_sandbox_and_cleans_up():
    res = self_test(Sandbox(enabled=False))
    assert len(res) == 8 and not any(r["pass"] for r in res)  # regression: negative checks must not pass vacuously
    assert "CASEFORGE_SECRET_PROBE" not in os.environ


def test_health_reports_sandbox_state():
    from fastapi.testclient import TestClient
    from caseforge.api.main import app
    h = TestClient(app).get("/health").json()
    assert h["sandbox"]["enabled"] is False and h["sandbox"]["ready"] is False
