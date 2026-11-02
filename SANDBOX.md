# Sandbox for LLM agents

This feature lets the agent loop run short pieces of Python that the model wrote, such as evidence aggregation or grouping logic, without trusting that code. It is intentionally read-only: it cannot change a score, approve a case, or reach the network.

## Supported runtimes
CaseForge looks for a container runtime in this order: `docker`, then `podman`, then `nerdctl` (or `CASEFORGE_SANDBOX_RUNTIME`). Use any runtime that supports Docker-compatible `run` commands.

## Setup
```bash
# install Docker Desktop, Podman Desktop, or Rancher Desktop, then start the runtime
python -m caseforge.harness sandbox-setup
python -m caseforge.harness sandbox-check
CASEFORGE_SANDBOX=on CASEFORGE_AGENTIC=on python -m caseforge.api.main
```

The `sandbox-check` command performs a real isolation self-test: it attempts network denial, filesystem writes, host-environment reads, memory pressure, runaway loops, output floods, and execution as root. Do not enable the sandbox until every line passes.

## How it isolates
Each run is a throw-away container (`--rm`) with: `--network=none`, a read-only root filesystem, a small `noexec` tmpfs, no mounts, `--cap-drop=ALL`, `no-new-privileges`, user `nobody`, memory and CPU limits, a hard timeout, and output caps. Code and data are passed over stdin as JSON and the container starts from a fixed bootstrap, so no host paths are involved and model text is not exposed in the command line.

## Fail closed
If no runtime is available or the image is missing, the `run_python` tool is unavailable and the case still completes normally. The health endpoint reports sandbox readiness details.

## Settings
`CASEFORGE_SANDBOX=on`, `CASEFORGE_SANDBOX_RUNTIME`, `CASEFORGE_SANDBOX_IMAGE` (default `python:3.12-slim`), `CASEFORGE_SANDBOX_MEMORY` (256m), `CASEFORGE_SANDBOX_CPUS` (1), `CASEFORGE_SANDBOX_TIMEOUT` (20 seconds).

## Honest limits
- Verified: the hardened command, the stdin protocol, timeouts, output caps, fail-closed behavior, and tool wiring have been tested in a Linux-style environment with a fake container CLI.
- Not verified: a real container run in every OS and every runtime. Use `sandbox-check` on your machine before trusting the sandbox in production.
- Containers share a kernel with their VM; they are a practical safeguard for casual untrusted code, not a guarantee against a determined attacker.
- Python only. No packages beyond the standard library are available inside the sandbox.
