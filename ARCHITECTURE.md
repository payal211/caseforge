# CaseForge and GECX: system guide

This guide describes what is implemented today, how a case moves through the system, what each domain scenario demonstrates, and which capabilities remain future work.

## What is running today

CaseForge is the investigation and human-review service. A Google ADK customer agent (the local GECX-style integration) can create and track card disputes through a customer-safe API. That request starts the same CaseForge workflow that the analyst console uses. The customer agent does not run approvals; the analyst console is the human-in-the-loop (HITL) surface.

The browser UI is a single React application with two separate experiences:

- **Customer agent:** simulated customer identity, conversation, dispute list, and customer-safe outcome.
- **Analyst console:** domain/scenario picker, evidence, deterministic score explanation, worker findings and trace, and approve/reject/override controls.

The UI is served by FastAPI at `/ui/`. Removing the React app would also remove the current analyst approval console. The optional `adk web` command is a developer UI for chatting with the ADK agent; it is not a case-review or approval console. For that reason the React app is retained as the analyst surface.

## Architecture by layer

| Layer | Technology | Responsibility |
|---|---|---|
| Customer interface | React, Vite-built static assets | Displays the demo customer chat, customer-safe dispute list, and polling updates. The account picker is only a demo identity selector. |
| Analyst interface | React, served by FastAPI StaticFiles | Shows case queue, evidence, score math, policy citations, agent findings, audit trace, and human decisions. Reviewer name is a demo label, not authentication. |
| Customer agent | Google ADK `LlmAgent`; Gemini or LiteLLM-to-Ollama; scripted fallback for offline demo | Interprets a customer message and may call only `list_recent_transactions`, `open_dispute`, and `check_dispute_status`. Its account comes from ADK session state, not chat text. |
| API | FastAPI and Pydantic | `/cx` exposes customer-scoped operations and customer-safe responses. `/cases` and `/cases/{id}/decision` expose analyst case operations. The GECX assistant routes are under `/cx/assistant`. |
| Workflow orchestration | LangGraph | Runs the shared case workflow in order: gather evidence → retrieve policy → guard untrusted inputs → calculate rule-based analysis → optional second opinion → specialist investigation → critic → draft case artifacts. |
| Supervisor and workers | `InvestigationSupervisor` with bounded sequential worker runs, using the configured LLM | Chooses specialist roles from the domain. Workers have scoped tool lists and budgets; they are advisory and cannot set scores or decide cases. These are role-specialized runs, not separately deployed models or autonomous services. |
| Tool boundary | MCP Python SDK over per-investigation stdio | The worker can call read-only evidence, entity/record lookup, and document-search tools. MCP schemas restrict allowed sources and fields; lookup is scoped to the current entity/account. Calls and outcomes are summarized in the trace. |
| Domain rules and data | Python domain packs, YAML declarative pack, CSV connectors | Defines signals, evidence weights, recommendation bands, artifacts, scenario data, and allowed source fields. SQL, REST, and Parquet connectors are available as alternate data sources. |
| Policy retrieval | Local Markdown sections with a lightweight TF-IDF `DocIndex` | Retrieves relevant policy/manual excerpts as citations. This is lexical retrieval, not embedding/vector search. |
| Deterministic controls | Python rules, guardrails, and finding critic | Computes score from weighted evidence, caps it, filters unsafe/ungrounded notes, and keeps decision authority outside the LLM. |
| Persistence and audit | JSON case files plus append-only JSONL audit by default; optional SQLAlchemy/PostgreSQL backend | Stores case state and timestamps, worker/tool trace, guardrail events, and human decision. Current demo reset clears the selected store and its audit log. |
| Model layer | Ollama native `/api/chat` tool calling and `/api/generate` narrative; Google ADK model for customer chat | Produces advisory findings or customer-facing text. A configured live investigation model must support tool calling. Model output does not control the deterministic score or analyst decision. |

## End-to-end request flow

1. A customer selects a **demo account** and starts an ADK session. A production GECX deployment must supply the account from verified identity/session claims.
2. The ADK agent calls a CaseForge customer tool. Transaction lookup returns only customer-safe transaction fields.
3. When a dispute is opened, `/cx/disputes` checks that the transaction belongs to the account, then starts the BFSI investigation.
4. The CaseForge workflow gathers evidence from the configured pack, searches policy, scans untrusted input, and computes the risk score deterministically.
5. The supervisor routes work to domain specialists. Each worker receives a narrow role and MCP tools, then returns concise notes citing successful tool calls. The critic accepts only safe notes with valid citations from that worker.
6. CaseForge drafts a summary and any domain artifacts, stores the case as `pending_approval`, and records audit events.
7. An analyst reviews the evidence and trace in the separate analyst console and approves, rejects, or overrides. Only this human decision changes the case from pending.
8. The customer agent polls the account-scoped customer API and sees a safe status/message after the reviewer decision. Internal scores, evidence, and analyst notes are not returned to the customer.

The analyst-side `approved`/`rejected` states describe whether the reviewer accepted or rejected **CaseForge's recommendation**. They do not directly mean that the customer dispute itself was approved or denied. The final action and customer-safe message describe that outcome.

## Domain scenarios and agent objectives

### Banking and card disputes (`bfsi`)

**Objective:** help a fraud analyst decide what to review by corroborating transaction evidence and dispute policy; the customer agent can open and track a dispute, never decide it.

- `TXN-9001` demonstrates a high-risk cross-border dispute: abnormal amount, new device, foreign location, transaction velocity, shared device, and off-hours activity. The current sample contributes 105 raw points and displays 100 after the cap.
- `TXN-9003` demonstrates an intermediate score and analyst verification.
- `TXN-9002` demonstrates a disputed transaction with no weighted fraud signals.

**Workers:** `fraud_forensics` checks account-scoped transaction/device history; `policy_analyst` searches dispute-policy guidance. The score bands and points come from the BFSI pack, not the LLM.

### Insurance claims (`claims`)

**Objective:** help an adjuster prioritize routine, documentation-review, or special-investigation cases; CaseForge does not approve or pay claims.

- `CLM-9001` demonstrates claim burst, new provider, shared payout account, and other risk signals; the recommendation is special investigation.
- `CLM-9003` demonstrates high value with fewer risk signals and a senior-adjuster recommendation.
- `CLM-9002` demonstrates a routine repair with no weighted signals.

**Workers:** `claims_forensics` checks claim/policy history and provider signals; `coverage_policy` searches the available claims policy text. This domain is defined as a YAML pack and uses the same shared workflow as the Python packs.

### Manufacturing maintenance

**Objective:** help an engineer prioritize inspection or maintenance using sensor drift and manual guidance. It only drafts a work order; no PLC/OT control is connected.

- `PUMP-07` demonstrates simultaneous vibration and temperature drift, matching the bearing-wear manual pattern.
- `COMP-02` demonstrates pressure/current drift and a lower-severity inspection recommendation.
- `PUMP-03` demonstrates stable telemetry and continued monitoring.

**Workers:** `telemetry_diagnostics` checks the machine's sensor history; `maintenance_policy` searches manual guidance.

## What the analyst sees as “LLM reasoning”

The console shows a reviewable explanation, not hidden model chain-of-thought:

- deterministic signal names, evidence details, point contributions, raw score, cap, and action bands;
- each worker's **objective**, state, and tool-call count;
- successful/failed tool steps, redaction counts, concise tool-result summaries, and the worker's cited notes;
- critic acceptance/rejection counts, policy citations, guardrail alerts, and the eventual human decision.

The model's natural-language notes are short claims tied to MCP tool-call IDs. Raw private reasoning is neither requested nor persisted. This is deliberate: the appropriate audit record is evidence, tool provenance, policy basis, rule calculations, and human rationale—not private scratchpad text. Prompts/replies are not currently stored as full transcripts.

## Identity, safety, and current limits

- The account selector and reviewer-name field are demo identity labels, **not authentication**. A nonblank analyst name is recorded with each decision, but it is self-declared. The account-scoped API checks ownership, but a production deployment still needs verified identity, authorization, service-to-service authentication, and analyst RBAC.
- GECX customer chat is currently for BFSI card disputes. Claims needs a claimant-facing intake/status toolset; manufacturing should have a technician/engineer workflow, not a consumer dispute bot.
- Workers run sequentially under the configured model with bounded MCP tools. They are not separate hosted agent services, and no external bank, claims-management, ERP/CMMS, Slack, or ServiceNow integration is configured.
- The risk score is deterministic, but the rules, sample data, and thresholds are demonstrations and require domain-owner validation before real operations.
- The deterministic critic validates note safety and citation provenance; it is not a semantic proof that every model claim is true.
- TF-IDF policy retrieval can miss paraphrases. Vector/hybrid retrieval and source/version governance are future work.
- Productivity baselines are assumptions, not measured outcomes.

## Future scope

1. Add real customer authentication and analyst identity/RBAC; distinguish demo roles from verified principals in the audit record.
2. Add claims intake/status interactions and a separate manufacturing engineer workflow, each with a domain-specific identity and tool boundary.
3. Add production connectors with least-privilege credentials, retries, timeouts, idempotency, and source freshness tracking.
4. Add durable conversation/workflow state, resumable human approvals, notifications, and escalation SLAs.
5. Add versioned policy/rule management, domain-owner review, calibration, fairness/error analysis, and regression evaluations.
6. Add richer observability: model/version metadata, latency, tool success/error codes, trace correlation IDs, redaction policy, and immutable retention controls.
7. Evaluate hybrid/vector retrieval and an independent semantic evaluator; keep final consequential decisions with authorized humans.

## Run and reset the local demo (Windows Command Prompt)

Start Ollama and verify the chosen model advertises tool support with `ollama show llama3.1:latest`. Then:

```bat
set "GECX_PROVIDER=ollama"
set "GECX_MODEL=llama3.1:latest"
set "OLLAMA_MODEL=llama3.1:latest"
uvicorn caseforge.api.main:app --reload
```

Open `http://localhost:8000/ui/`. Use **Customer agent** to open a dispute, then switch to **Analyst console** to inspect and decide it. The customer view shows only the safe outcome. The **Reset demo** button is destructive: it removes all cases and audit records in the configured data backend.
