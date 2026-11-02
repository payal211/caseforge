# Developer guide

This guide is the default onboarding path for CaseForge. It avoids shell-specific startup scripts and focuses on the real developer workflow: create a virtual environment, install dependencies, run the doctor, launch the API, and start using the demo.

## 1. Prerequisites
- Python 3.11 or 3.12
- A local package manager such as `pip`
- Optional: Docker for PostgreSQL or sandboxed agent execution
- Optional: Ollama for local LLM narrative generation

## 2. Create and activate the environment
```bash
python -m venv .venv
# Windows: activate the venv in your shell
# macOS/Linux: source .venv/bin/activate
```

## 3. Install dependencies
```bash
pip install -r requirements.txt
```

## 4. Validate the environment
```bash
python -m caseforge.doctor
```

`python -m caseforge.doctor` runs environment and setup checks. It verifies that the project dependencies, model access, and runtime assumptions are in a usable state before you begin investigations. Address each `[FAIL]` before proceeding. `[WARN]` items can be reviewed later, but they are not blockers.

## 5. Run the demo locally
```bash
python -m caseforge.cli
```

`python -m caseforge.cli` is the terminal demo entry point. It runs the built-in investigation scenarios across the available packs and prints the risk assessment and evidence for each subject.

## 6. Start the API and UI
```bash
uvicorn caseforge.api.main:app --reload
```

`uvicorn caseforge.api.main:app --reload` starts the FastAPI application in development mode. It serves the browser console and exposes the REST API and Swagger docs.

Open:
- http://localhost:8000/ for the console UI
- http://localhost:8000/docs for the FastAPI docs

## 7. Test the project
```bash
LLM_MODE=mock python -m pytest -q
```

This is the baseline verification path used for CI-like validation without requiring a live model.

## 8. Optional: Ollama mode
If you want narrative generation from a local model:

```bash
ollama pull llama3.1:8b
LLM_MODE=auto python -m caseforge.cli
```

Keep Ollama running while the app uses the model.

## 9. Optional: PostgreSQL storage
This project can store case files and audit events in PostgreSQL instead of the default JSON files.

```bash
docker compose up -d
export CASEFORGE_DB_URL="postgresql+psycopg://caseforge:caseforge@localhost:5432/caseforge"
# Windows PowerShell
# $env:CASEFORGE_DB_URL="postgresql+psycopg://caseforge:caseforge@localhost:5432/caseforge"
uvicorn caseforge.api.main:app
```

Check the health endpoint to confirm the backend is `postgresql`.

## 10. Optional: SQL / REST / Parquet sources
Set one of the relevant environment variables:

```bash
export CASEFORGE_BFSI_DB_URL="..."
export CASEFORGE_MANUFACTURING_DB_URL="..."
export CASEFORGE_BFSI_TRANSACTIONS_URL="..."
export CASEFORGE_BFSI_ACCOUNTS_URL="..."
export CASEFORGE_MANUFACTURING_SENSORS_URL="..."
```

Source priority is:
1. SQL
2. REST
3. Parquet
4. CSV

## 11. Sandbox for model-written code
If you want the agent loop to run small model-generated Python snippets in a hardened container:

```bash
python -m caseforge.harness sandbox-setup
python -m caseforge.harness sandbox-check
CASEFORGE_SANDBOX=on CASEFORGE_AGENTIC=on uvicorn caseforge.api.main:app --reload
```

See [SANDBOX.md](SANDBOX.md) for the full isolation and safety model.

## 12. Useful commands
```bash
python -m caseforge.mcp_server
python scripts/generate_data.py
python scripts/csv_to_parquet.py
```

Command purpose summary:
- `python -m caseforge.mcp_server`: exposes the Model Context Protocol server used by external tools.
- `python scripts/generate_data.py`: creates or refreshes the demo data used by the case packs.
- `python scripts/csv_to_parquet.py`: converts CSV datasets to Parquet format for alternate source loading.

## 13. Project map
- [caseforge/cli.py](caseforge/cli.py): terminal demo entry point.
- [caseforge/doctor.py](caseforge/doctor.py): setup and environment health check.
- [caseforge/api/main.py](caseforge/api/main.py): FastAPI app and API surface.
- [caseforge/core/orchestrator.py](caseforge/core/orchestrator.py): main investigation flow.
- [caseforge/core/audit.py](caseforge/core/audit.py): audit trail persistence.
- [caseforge/core/guardrails.py](caseforge/core/guardrails.py): suspicious-content detection.
- [caseforge/packs/](caseforge/packs/): domain definitions and source data.
- [caseforge/harness/](caseforge/harness/): tests, pack generation, sandbox helpers.
- [frontend/src/](frontend/src/): review console frontend.

## 14. Suggested workflow for a new contributor
1. Create a virtual environment.
2. Install requirements.
3. Run `python -m caseforge.doctor`.
4. Run `LLM_MODE=mock python -m pytest -q`.
5. Launch the API with `uvicorn`.
6. Open the console and investigate one BFSI and one manufacturing case.
7. Try one guardrail or attack scenario before broadening scope.

This gives a realistic developer setup without relying on any legacy Windows-specific startup scripts.
