# CaseForge x GECX: customer dispute assistant (local demo with Google ADK)

## Use case
A bank customer chats with a **customer-experience agent** about a card charge they don't recognise.
The agent opens a dispute in **CaseForge**, which runs the multi-agent investigation (evidence, policy
retrieval, guardrails, risk score). A **human fraud analyst** approves or overrides. Only then is the
outcome released back to the customer through the same agent.

```
Customer ─chat─▶ GECX-style agent (Google ADK) ──HTTP /cx──▶ CaseForge ──▶ analyst console (/ui)
                 tools: list_recent_transactions,            investigate +          approve / reject /
                        open_dispute,                        guardrails + audit     override (human only)
                        check_dispute_status       ◀─ customer-safe status ─┘
```

## Design rules (enforced in `caseforge/api/cx.py`, covered by `tests/test_cx_channel.py`)
| Rule | How |
|---|---|
| Agent can open and track, never decide | `/cx` has no approve/reject route; only `/cases/{id}/decision` decides |
| No cross-account access | Ownership checked server-side; account comes from session state, not chat text; "not yours" and "doesn't exist" look identical |
| No internal leakage | Customer sees only `reference`, `status`, `customer_message`; score, evidence, flags stay internal |
| Outcome only after a human | Approved text is released only once status is approved; reject/override shows "specialist will contact you" and never leaks the AI recommendation |
| Customer text is untrusted | Scanned by the existing guardrails, redacted in the audit trail, never touches the score |

## Run it
**Integrated CaseForge browser demo:** run `uvicorn caseforge.api.main:app --reload`, open
http://localhost:8000/ui/, and choose **Customer agent**. Customer chat and analyst review now
share the same running API and case queue. This is the recommended demo flow. Choose
**Analyst console** to review or decide a dispute opened from chat. The account picker uses
synthetic demo identities and does not provide production authentication.

On Windows Command Prompt, select Ollama before starting the API:
```bat
set "GECX_PROVIDER=ollama"
set "GECX_MODEL=llama3.1:latest"
set "OLLAMA_MODEL=llama3.1:latest"
uvicorn caseforge.api.main:app --reload
```

The terminal-only walkthrough remains useful for presenting scripted scenes:
```bash
pip install -r requirements.txt google-adk
python gecx/demo.py            # offline: scripted model stands in for Gemini, no key needed
```
The demo walks 7 scenes: dispute, status while pending, analyst approval, outcome release,
prompt-injection attempt, cross-account attempt, customer vs analyst view.
It is a terminal walkthrough, not a browser chat UI. While it is running, open the printed
**Analyst UI** URL to review the same temporary demo cases; the UI is the reviewer console,
not the customer chat interface.

**With Gemini:** `export GOOGLE_API_KEY=...` (optionally `GECX_MODEL=...`) and rerun. Same tools, same instruction.

**With Ollama (Windows PowerShell):** use an installed model that advertises tool support.
For example, `ollama show llama3.1:latest` should list `tools` under Capabilities.
The installed `llama3.1:latest` model on this machine does so. Gemma has not been checked
because it is not installed here.
In the terminal used to run the demo:
```powershell
$env:LLM_MODE = "auto"
$env:OLLAMA_MODEL = "llama3.1:latest"
$env:GECX_PROVIDER = "ollama"
$env:GECX_MODEL = "llama3.1:latest"
python gecx/demo.py
```
`OLLAMA_MODEL` selects the model for CaseForge's investigation summaries; `GECX_MODEL`
selects the ADK customer agent model. `GECX_PROVIDER=ollama` routes that agent through
LiteLLM to the local Ollama server at `http://localhost:11434` (override with `OLLAMA_URL`
if needed). Check any alternate model with `ollama show <model>` and use it for the agent
only if its Capabilities include `tools`.

**Interactive ADK UI** (two terminals):
```bash
uvicorn caseforge.api.main:app            # terminal 1
cd gecx && adk web                        # terminal 2, pick caseforge_dispute_assistant
```
`adk web` needs a real model key, and the agent reads the customer from session state
`account_id`; set it in the ADK dev UI's session state (e.g. `{"account_id": "ACC-1001"}`).
Open the analyst console at http://localhost:8000/ui/ to approve cases.
For local Ollama instead of Gemini, set `GECX_PROVIDER=ollama` and `GECX_MODEL=llama3.1:latest`
in both terminals before starting them.

## Moving to managed GECX / CX Agent Studio
`python gecx/export_openapi.py` writes `gecx/openapi/caseforge-cx.json`, containing only the `/cx`
paths. Register that spec as an OpenAPI tool on your agent in CX Agent Studio, put the authenticated
customer's account ID in a session parameter, and reuse the `INSTRUCTION` text from
`caseforge_dispute_agent/agent.py` as the agent instructions. I haven't tested this step against a
live GECX project, so check the console's current tool-registration flow.
For production, add real authentication on `/cx` (e.g. service-to-service tokens); today it trusts
the caller to supply the authenticated `account_id`.

## Honest limits
- The offline model is scripted (regex routing), so it demonstrates the plumbing and safety rules,
  not conversational quality. Test wording with Gemini.
- The ADK Ollama option uses LiteLLM; Ollama must be running and the selected model must list
  `tools` in `ollama show <model>` for the customer agent's tool calls.
- Some models may decline to call a tool for the hostile-input scene. The demo then submits
  that same statement directly to the CX API so its backend guardrails can still be shown;
  the output labels this fallback explicitly.
- Demo data is the repo's synthetic CSVs.
