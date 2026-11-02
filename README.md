# CaseForge

CaseForge is a shared investigation platform for operational risk decisions. It combines evidence gathering, retrieval, guardrails, reasoning, and an approval workflow so a human reviewer can decide with a clear audit trail.

Built around two domain packs:
- **BFSI**: fraud and dispute investigation across transactions, identity/device signals, and policy documents.
- **Manufacturing**: predictive maintenance root-cause analysis using sensor signals, manuals, and work-order context.

The pipeline is: gather -> retrieve -> reason -> draft -> human approval. It can run without an LLM using deterministic fallbacks, and it can use Ollama when available.

The harness is the operational safety layer behind the platform. It does not replace the business rules or the human reviewer — it makes sure new risk logic can be added, tested, and trusted before it is used in live decisions.

In practical terms, the harness lets teams define new industry rules, validate them against real-world scenarios, and check whether they are safe, explainable, and consistent. This matters in regulated or high-risk environments because a bad rule can create false alarms or miss serious issues. The harness gives teams a controlled way to launch new policies without damaging trust or causing operational disruption.

It is especially valuable when:

a new fraud or claim pattern appears
a business wants to extend the platform to a new domain
teams need repeatable checks before changing live decision logic
they need to test suspicious or adversarial inputs before they reach real operations

In short, the harness turns a prototype into a governable operational platform.


In live operations, risk logic is never static. New fraud patterns, claim behaviors, and equipment failure signatures appear every day. The harness gives teams a structured way to add, validate, and govern new rules before they impact real decisions. It reduces operational risk, improves trust in the system, and ensures that new domain logic is tested, explainable, and safe to deploy.


## Developer quick start
```bash
python -m venv .venv
# Windows: activate the venv in your shell
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
python -m caseforge.doctor
python -m caseforge.cli
uvicorn caseforge.api.main:app --reload
```

What each command does:
- `python -m venv .venv`: creates a local Python environment for the project.
- `pip install -r requirements.txt`: installs the app and its dependencies.
- `python -m caseforge.doctor`: runs a health check for Python, environment variables, model access, and setup readiness.
- `python -m caseforge.cli`: runs the built-in terminal demo across the available domain packs.
- `uvicorn caseforge.api.main:app --reload`: starts the FastAPI app in development mode.

Then open:
- API docs: http://localhost:8000/docs
- Console UI: http://localhost:8000/ui/

For a deeper setup and environment configuration walkthrough, see [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

## What the project does
CaseForge creates a case file for a domain subject, gathers evidence, checks for suspicious or poisoned inputs, and produces a recommendation with citations and artifacts. Each case is saved with decision state and audit records.

## Architecture

CaseForge follows a layered design:

```text
+---------------------------+
| User / Reviewer           |
| UI Console + API          |
+-------------+-------------+
              |
              v
+---------------------------+
| API Layer                 |
| FastAPI + Decision Routes |
+-------------+-------------+
              |
              v
+---------------------------+
| Orchestration Layer       |
| Orchestrator + LangGraph  |
| gather -> retrieve ->     |
| reason -> draft -> review |
+-------------+-------------+
              |
      +-------+--------+
      |                |
      v                v
+----------------+  +-----------------------+
| Domain Packs   |  | Guardrails / Audit    |
| BFSI / Claims  |  | Safety + traceability |
| Manufacturing  |  +-----------------------+
+-------+--------+
        |
        v
+----------------------------+
| Data Sources               |
| SQL / REST / Parquet / CSV |
+----------------------------+
```

Core responsibilities:
- Domain packs define how a business area behaves and what data to inspect.
- The orchestrator manages the investigation workflow from evidence collection to recommendation.
- Guardrails flag suspicious or adversarial content before it can influence decisions.
- The audit layer records every significant event so decisions are explainable and reviewable.
- The API and UI provide the human decision layer for approve, reject, or override actions.
- The harness validates new packs, scenarios, and edge cases before operational rollout.

## Project map: what each main file is for
- [caseforge/cli.py](caseforge/cli.py): quick terminal demo entry point; runs the investigation pipeline for one case or the full sample set.
- [caseforge/doctor.py](caseforge/doctor.py): environment and dependency validation script to check whether the app is ready to run.
- [caseforge/api/main.py](caseforge/api/main.py): FastAPI app that serves the console, exposes the API, manages cases, and handles review decisions.
- [caseforge/core/orchestrator.py](caseforge/core/orchestrator.py): main workflow engine that loads packs, runs the investigation graph, saves results, and computes metrics.
- [caseforge/core/audit.py](caseforge/core/audit.py): stores case and decision events for the audit trail.
- [caseforge/core/guardrails.py](caseforge/core/guardrails.py): checks for suspicious or malicious content and flags risky inputs.
- [caseforge/core/llm.py](caseforge/core/llm.py): wraps the LLM integration used to generate narrative summaries and model-backed reasoning.
- [caseforge/packs/](caseforge/packs/): domain plugins for BFSI, manufacturing, and new custom packs.
- [caseforge/mcp_server.py](caseforge/mcp_server.py): Model Context Protocol server for tool-style access to investigation data.
- [caseforge/harness/](caseforge/harness/): evaluation, pack generation, sandbox and runtime-check tools.
- [scripts/generate_data.py](scripts/generate_data.py): creates demo source data used by the example cases.
- [frontend/src/](frontend/src/): React console for reviewing cases in the browser.

## Core runtime
The project is structured around:
- `caseforge/core/orchestrator.py`: orchestrates the investigation graph and decision workflow.
- `caseforge/packs/`: domain-specific plug-ins for data and policies.
- `caseforge/api/main.py`: FastAPI app for the console and API.
- `caseforge/harness/`: evaluation, packaging, and sandbox tooling.
- `caseforge/core/audit.py`: immutable audit trail and event logging.

## Demo flow
1. Start the API and open the UI.
2. Pick a domain such as BFSI or manufacturing.
3. Investigate a subject like `TXN-9001` or `PUMP-07`.
4. Review evidence, citations, guardrail flags, and the draft summary.
5. Approve, reject, or override the recommendation.
6. Inspect the stored case and audit trail.

## API basics
```bash
GET /domains
POST /cases {"domain":"bfsi","subject_id":"TXN-9001"}
POST /cases/{id}/decision {"reviewer":"you","outcome":"approve"}
GET /cases/{id}/audit
GET /metrics
```

## Optional integrations
### Ollama
```bash
ollama pull llama3.1:8b
LLM_MODE=auto python -m caseforge.cli
```

### PostgreSQL
```bash
docker compose up -d
export CASEFORGE_DB_URL="postgresql+psycopg://caseforge:caseforge@localhost:5432/caseforge"
uvicorn caseforge.api.main:app
```

### SQL and REST connectors
CaseForge can read source data from SQL tables, REST APIs, Parquet files, or CSV files. The priority is SQL > REST > Parquet > CSV.

## Security and guardrails
The project includes built-in guardrail checks for prompt injection, poisoned documents, and suspicious tool output. The system records flags and requires a human decision even when the score remains unchanged.

## MCP server
```bash
python -m caseforge.mcp_server
```

This exposes a stdio protocol for tools such as `list_domains`, `investigate_case`, `get_case`, and `get_audit_trail` without exposing a direct approval tool.

## Profiles and packs
Use the existing packs or add a new domain by creating a package under `caseforge/packs/<name>/` and exposing a `PACK` object.

## Testing and validation
```bash
LLM_MODE=mock python -m pytest -q
```

## Additional docs
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
- [GUARDRAILS.md](GUARDRAILS.md)
- [OPENJEV.md](OPENJEV.md)
- [HARNESS.md](HARNESS.md)
- [SANDBOX.md](SANDBOX.md)

## Known gaps
- Kafka connector is not implemented.
- Embedding-based retrieval is not yet in place.
- Manual-time baselines in metrics are assumed values and should be replaced with measured data.
