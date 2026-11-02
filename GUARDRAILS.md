# Guardrails

**Principle:** decisions are made by deterministic code, not by the LLM. The LLM only writes the narrative,
and a human approves every case. Guardrails are defence in depth around that.

| Layer | What it does | Where |
|---|---|---|
| Deterministic scoring | Score and action come from weighted signals; text in data cannot change them | `packs/*/pack.py` |
| Guard agent | Scans evidence, retrieved documents and record fields (merchant names, manuals, policies); redacts matches, flags the case | `core/agents.py` (GuardAgent) |
| Hardened system prompt | Data is fenced in `<untrusted_data>`; the model may not change the score, claim actions were taken, or emit encoded text | `core/guardrails.py` |
| Output validator | Rejects LLM text that obeys injections, claims an action happened, contradicts the score, or hides base64 blobs; falls back to the rule-based summary | `core/guardrails.py` |
| Human approval | No auto-approve path; decisions are final and audited | `core/orchestrator.py` |
| MCP design | The MCP server has no approve/reject tool | `mcp_server.py` |

## Attack catalogue covered by `tests/test_guardrails.py`
Instruction override, role hijack and prompt leak, score tampering, fake closing tags, encoded (base64) payloads,
injected via: transaction merchant field, poisoned policy document, poisoned maintenance manual (including a fake
"Step"), malformed subject ids; plus hostile LLM outputs (claims approval, obeys injection, wrong score,
encoded leak, fake tags).

## Known limits
Pattern matching is a first filter: a novel phrasing can slip past it. That is why scores/actions never depend on
LLM text and a human approves. Extend `PATTERNS` and the tests as new attacks appear. Optional next step: run the
same attack corpus through promptfoo (eval mode) against a local Ollama target in CI, and add an `llm-rubric` check
for leaks that string matching cannot see (for example, encoded secrets).
