# CaseForge as a harness for any industry

CaseForge is split in two. The **harness** (everything industry-neutral) and the **pack** (what your industry adds).

| Harness gives you, for free | A pack provides |
|---|---|
| Investigation pipeline (gather, retrieve, guard, reason, second opinion, agent loop, draft) | Where the data lives (CSV, Parquet, SQL, REST) |
| Prompt-injection guardrails, redaction, output validation | Risk rules and weights |
| Human approve / reject / override, audit trail, atomic decisions | Policy or manual documents (`## Section` headings become citations) |
| Case storage (JSON files or PostgreSQL), REST API, React console, MCP server | Score bands to actions, draft message templates |
| Default LLM agent via case-scoped MCP read-only tools, budgets, grounded notes | A few scenarios with the expected outcome |
| Eval harness and attack tests that gate CI | |

## Add an industry in four commands (no Python)
```bash
python -m caseforge.harness new-pack retail_returns      # scaffold a runnable pack with sample data
# edit caseforge/packs/retail_returns/: data/records.csv, docs/policy.md, pack.yaml
python -m caseforge.harness check-pack retail_returns    # validates files, columns, scenarios, injection attacks
uvicorn caseforge.api.main:app                           # it appears in the console automatically
```
Included proof: `caseforge/packs/claims/` (insurance claim triage) is defined **only** in YAML plus a policy document, and passes the same
checks as the hand-written fraud and maintenance packs.

## Rule types (pack.yaml `signals`)
`zscore` (amount unusually far from this entity's history), `new_value` (never seen before), `count_window` (bursts), `shared_across`
(one value used by many entities), `time_of_day`, `threshold`, `differs_from_entity` (record vs profile). Each adds weighted points to a
0-100 score; `actions` map score bands to recommendations. Scores are deterministic: no model decides them.

## When you need Python
Time-series or custom logic (like the maintenance pack) uses the Python `DomainPack` API (`caseforge/packs/base.py`, about 30 lines of contract,
one pack file of about 125 lines). Both kinds are discovered automatically and behave the same in the console, API, MCP server and evals.

## Run the checks
`python -m caseforge.harness evals` runs every pack's scenarios and all attacks and exits non-zero on failure (use it in CI).
The supervisor routes each live investigation to domain specialists by default and connects them
to one per-case MCP stdio server. BFSI uses fraud-forensics and policy-analysis workers;
manufacturing uses telemetry-diagnostics and maintenance-policy workers; declarative packs get
record-forensics and policy workers. The workers can call only `get_evidence`,
`search_documents`, and `lookup` with account/entity-scoped allowlisted fields. Step and tool
budgets apply; every note must cite a successful tool call. A deterministic evaluator rejects
unsafe notes or citations to failed/other-worker calls. Workers cannot change deterministic
scoring or approve a case. The case and audit log preserve the worker and tool trace, then the
case pauses for a human decision. Ollama and a working model with native tool-call support are
required for live investigations; tests and the explicitly scripted offline demo use
`LLM_MODE=mock`.

## Honest limits
Declarative packs cover record-style cases (judge one record against its entity's history). Rules are simple statistics, not trained models, and are
untuned on real data. Agent-loop quality with a small local model is untested (tests use a scripted model). All demo data is synthetic.
