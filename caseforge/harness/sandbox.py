"""Sandboxed code execution for LLM agents, on any OS that has a Docker-compatible container runtime.

  Windows        Docker Desktop (WSL2 backend), Podman Desktop, Rancher Desktop, or Docker Engine inside WSL2
  macOS / Linux  Colima, Docker, Podman, Rancher Desktop (Colima is NOT available on Windows)

The harness never talks to a specific product: it runs the standard `run` CLI of whichever runtime it
finds. Model-written Python runs in a throw-away container with no network, a read-only filesystem, no
mounts, dropped capabilities, a non-root user, and memory, CPU, process, output and time limits. Code
and data travel over stdin (no host paths, so Windows path quirks never apply). FAIL CLOSED: if no
runtime or image is available, the tool simply does not exist for the agent."""
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

# Fixed bootstrap: reads {"code","data"} from stdin, exposes `data`, runs the code. Never built from model text.
BOOTSTRAP = ("import sys,json;d=json.load(sys.stdin);g={'data':d['data'],'__name__':'__main__'};"
             "exec(compile(d['code'],'<agent>','exec'),g)")
RUNTIMES = ("docker", "podman", "nerdctl")
MAX_PAYLOAD_BYTES = 500_000
INSTALL_HINT = ("Windows: install Docker Desktop (WSL2 backend) or Podman Desktop and start it. "
                "macOS/Linux: Colima (brew install colima docker; colima start), Docker or Podman. "
                "Colima does not run on Windows.")


@dataclass
class SandboxConfig:
    image: str = "python:3.12-slim"
    memory: str = "256m"
    cpus: str = "1"
    pids: int = 64
    timeout: int = 20
    grace: int = 10  # extra seconds for the container CLI before we kill the container ourselves
    max_output: int = 8000
    tmpfs_size: str = "32m"

    @classmethod
    def from_env(cls) -> "SandboxConfig":
        e = os.getenv
        return cls(image=e("CASEFORGE_SANDBOX_IMAGE", cls.image), memory=e("CASEFORGE_SANDBOX_MEMORY", cls.memory),
                   cpus=e("CASEFORGE_SANDBOX_CPUS", cls.cpus), timeout=int(e("CASEFORGE_SANDBOX_TIMEOUT", cls.timeout)))


@dataclass
class SandboxResult:
    ok: bool
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False
    runtime: str = ""
    seconds: float = 0.0


def detect_runtime() -> list[str] | None:
    """CASEFORGE_SANDBOX_RUNTIME (a name or full command) wins; otherwise first of docker, podman, nerdctl on PATH."""
    forced = os.getenv("CASEFORGE_SANDBOX_RUNTIME")
    if forced:
        parts = shlex.split(forced, posix=(os.name != "nt"))
        return parts if parts and (shutil.which(parts[0]) or os.path.exists(parts[0])) else None
    for name in RUNTIMES:
        path = shutil.which(name)
        if path:
            return [path]
    return None


class Sandbox:
    def __init__(self, cfg: SandboxConfig | None = None, runtime_cmd: list[str] | None = None, enabled: bool = True):
        self.cfg, self.enabled = cfg or SandboxConfig.from_env(), enabled
        self.cmd = runtime_cmd if runtime_cmd is not None else (detect_runtime() if enabled else None)
        self._status: tuple[float, bool, str] | None = None

    @classmethod
    def from_env(cls) -> "Sandbox":
        return cls(enabled=os.getenv("CASEFORGE_SANDBOX", "off").lower() in {"on", "1", "true"})

    @property
    def runtime_name(self) -> str:
        return os.path.basename(self.cmd[-1]) if self.cmd else "none"

    # ------------------------------------------------------------ availability (fail closed)
    def status(self, fresh: bool = False) -> tuple[bool, str]:
        if not self.enabled:
            return False, "sandbox is off (set CASEFORGE_SANDBOX=on)"
        if self._status and not fresh and time.time() - self._status[0] < 60:
            return self._status[1], self._status[2]
        ok, why = self._probe()
        self._status = (time.time(), ok, why)
        return ok, why

    def _probe(self) -> tuple[bool, str]:
        if not self.cmd:
            return False, "no container runtime found. " + INSTALL_HINT
        try:
            if subprocess.run([*self.cmd, "info"], capture_output=True, timeout=15).returncode != 0:
                return False, f"{self.runtime_name} is installed but not running. Start Docker Desktop / Podman Desktop (or 'colima start')."
            if subprocess.run([*self.cmd, "image", "inspect", self.cfg.image], capture_output=True, timeout=15).returncode != 0:
                return False, f"image {self.cfg.image} is not downloaded. Run: python -m caseforge.harness sandbox-setup"
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"{self.runtime_name} did not respond ({type(e).__name__})"
        return True, f"{self.runtime_name} ready with image {self.cfg.image}"

    @property
    def available(self) -> bool:
        return self.status()[0]

    # ------------------------------------------------------------ execution
    def build_run_args(self, name: str) -> list[str]:
        c = self.cfg
        return [*(self.cmd or []), "run", "--rm", "-i", "--name", name, "--pull=never",
                "--network=none", "--read-only", "--tmpfs", f"/tmp:rw,noexec,nosuid,size={c.tmpfs_size}",
                "--memory", c.memory, "--memory-swap", c.memory, "--cpus", c.cpus, "--pids-limit", str(c.pids),
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "65534:65534",
                c.image, "timeout", "-s", "KILL", str(c.timeout), "python", "-I", "-c", BOOTSTRAP]

    def run(self, code: str, data: dict | None = None) -> SandboxResult:
        ok, why = self.status()
        if not ok:
            return SandboxResult(False, None, stderr=f"sandbox unavailable: {why}")
        payload = json.dumps({"code": code, "data": data or {}}, default=str).encode("utf-8")
        if len(payload) > MAX_PAYLOAD_BYTES:
            return SandboxResult(False, None, stderr="code and data are too large for the sandbox")
        name = f"caseforge-sbx-{uuid.uuid4().hex[:12]}"
        t0, timed_out = time.perf_counter(), False
        try:
            p = subprocess.run(self.build_run_args(name), input=payload, capture_output=True,
                               timeout=self.cfg.timeout + self.cfg.grace)
            out, err, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            timed_out, out, err, rc = True, e.stdout or b"", e.stderr or b"", None
            for sub in (["kill", name], ["rm", "-f", name]):  # the CLI was killed; make sure the container dies too
                try:
                    subprocess.run([*self.cmd, *sub], capture_output=True, timeout=15)
                except Exception:
                    pass
        cap = self.cfg.max_output
        return SandboxResult(ok=(rc == 0 and not timed_out), exit_code=rc, stdout=out[:cap].decode("utf-8", "replace"),
                             stderr=err[:cap].decode("utf-8", "replace"), timed_out=timed_out or rc == 137,
                             truncated=len(out) > cap or len(err) > cap, runtime=self.runtime_name,
                             seconds=round(time.perf_counter() - t0, 2))


# ------------------------------------------------------------------ self-test (run this on the real machine)
def _ro(r): return not r.ok and ("Read-only" in r.stderr or "Errno 30" in r.stderr)


SELF_TESTS = [
    ("runs ordinary code", "print(sum(data['x']) * 2)", {"x": [1, 2, 3]}, lambda r: r.ok and r.stdout.strip() == "12"),
    ("is not root", "import os;print(os.getuid())", {}, lambda r: r.ok and r.stdout.strip() != "0"),
    ("has no network", "import urllib.request as u\nu.urlopen('http://1.1.1.1', timeout=3)", {},
     lambda r: not r.ok and "Traceback" in r.stderr),
    ("filesystem is read-only", "open('/etc/caseforge_test','w').write('x')", {}, _ro),
    ("host environment is not visible", "import os;print(os.environ.get('CASEFORGE_SECRET_PROBE','absent'))", {},
     lambda r: r.ok and r.stdout.strip() == "absent"),
    ("memory hog is stopped", "x = bytearray(2 * 1024**3)", {}, lambda r: not r.ok),
    ("infinite loop is stopped", "while True: pass", {}, lambda r: not r.ok and r.timed_out),
    ("output is capped", "print('A' * 100000)", {}, lambda r: r.truncated and len(r.stdout) <= 8000),
]


def self_test(sb: Sandbox) -> list[dict]:
    os.environ["CASEFORGE_SECRET_PROBE"] = "leaked"
    try:
        out = []
        for name, code, data, check in SELF_TESTS:
            r = sb.run(code, data)
            ran = r.exit_code is not None or r.timed_out  # a check can only pass if the code really executed
            out.append({"name": name, "pass": bool(ran and check(r)), "detail": (r.stderr or r.stdout)[-160:].replace("\n", " ")})
        return out
    finally:
        os.environ.pop("CASEFORGE_SECRET_PROBE", None)
