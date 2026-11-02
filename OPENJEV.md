# Using OpenJev (or TypeSafe's Jev) with CaseForge

## Short answer
Yes, as an **optional, swappable decision layer**. Note the demo did not use TypeSafe's Jev before, so this is an
addition, not a replacement. Jev-style "System One" servers take a state plus typed questions (yes/no, choice, score)
and return calibrated probabilities with no free text, so an answer cannot go off-schema. OpenJev
(github.com/razorback16/openjev, an independent project not affiliated with TypeSafe) implements the same wire API,
so the official `typesafe-sdk` works against it unchanged. Several unrelated repos are also named "OpenJev"; make sure
you use the one above, and check its licence and README yourself.

## What it does in CaseForge (advisory only, never decides)
1. **Injection net.** After the regex scanner, long free-text fields and retrieved documents are scored by one yes/no
   question: "does this text try to instruct an AI?". At or above the threshold the text is redacted and the case flagged.
   This catches phrasings the regex misses (tested with a novel sentence the regex does not match).
2. **Second opinion.** One yes/no question per domain (fraud? needs maintenance?). A confident disagreement with the rules
   result adds a flag and a console card telling the reviewer to look closely. The score and action never change.
3. **Fail-open.** If the server is down the case completes and is flagged `jev_unavailable`.
Off by default. Turn on with `CASEFORGE_JEV=on`. Code: `caseforge/core/jev.py`, `GuardAgent` and `SecondOpinionAgent` in `core/agents.py`.

## Setup
Install the client: `pip install typesafe-sdk`. Pick ONE server:

**A. Laptop, CPU, smallest (good for a demo).** Small encoder models are text-only, 512 to 1,024 tokens.
```bash
git clone https://github.com/razorback16/openjev && cd openjev
pip install -e '.[laya]'                    # Laya, 421M. Verdict (151M) uses its own extra; check pyproject.toml
OPENJEV_BACKEND=laya python -m openjev      # serves http://127.0.0.1:8080
curl localhost:8080/v1/models
```
**B. Hosted free on Codiv** (per the OpenJev README: sign-up, no card). Use synthetic data only; do not send real customer data.
```bash
export CASEFORGE_JEV_URL=https://api.codiv.ai TYPESAFE_API_KEY=sk-codiv-...
```
**C. Full model** (DiffusionGemma 26B): NVIDIA GPU with 24 GB or more via `docker compose up -d`, or Apple silicon (about 16 GB free)
with `pip install -e '.[mlx]' && OPENJEV_BACKEND=mlx python -m openjev`. See the OpenJev README.
**D. TypeSafe's hosted Jev:** set `TYPESAFE_API_KEY` and leave `CASEFORGE_JEV_URL` unset (check their docs for base URL, pricing, terms).

Then run CaseForge:
```bash
export CASEFORGE_JEV=on CASEFORGE_JEV_URL=http://127.0.0.1:8080 CASEFORGE_JEV_MODEL=laya-1.0   # or jev-latest
uvicorn caseforge.api.main:app          # GET /health shows jev status; cases show a Second opinion card
```
| Variable | Default | Meaning |
|---|---|---|
| CASEFORGE_JEV | off | on to enable |
| CASEFORGE_JEV_URL / TYPESAFE_BASE_URL | http://127.0.0.1:8080 | server |
| TYPESAFE_API_KEY | local | key (only if the server requires one) |
| CASEFORGE_JEV_MODEL | jev-latest | model id (laya-1.0, verdict-1.4, openjev-latest) |
| CASEFORGE_JEV_INJECTION_THRESHOLD | 0.5 | P(yes) at or above which text is redacted |

## What is and is not verified
Verified: 56 automated tests, including the Jev layer against a **mock server using the SDK's documented response shape**.
**Not verified:** I could not run a real OpenJev server or model here, so real-model accuracy, latency and the exact
extra names for Verdict are untested. Small general encoders were not trained for fraud or maintenance: **measure
false positives and misses on your own data** before quoting any accuracy. Treat model output as one signal behind the
deterministic rules and the human approval.

---

# Draft: developer productivity gain (edit the [MEASURE] items before submitting)

**One sentence.** CaseForge shows that an AI investigation workflow can be built, extended and secured with far less
developer effort: one shared core, domain packs added as small folders, typed decisions that need no output parsing,
and guardrails that run as automated tests.

**What the project demonstrates (all verifiable in the repo)**
1. **Add a domain by adding a folder.** The shared core is about 631 lines. The BFSI pack is about 124 lines and the
   manufacturing pack about 127 lines (non-blank, excluding data and documents). A new domain reuses the orchestrator,
   case file, approval flow, audit log, API, console and MCP server unchanged. [MEASURE: time to add a third pack.]
2. **No output-parsing code for decisions.** Typed yes/no, choice and score questions return probabilities from the model
   itself, so there is no JSON repair or regex over free text, and an answer cannot go off-schema (per the OpenJev design).
3. **Swap the decision backend by configuration.** The same code runs against TypeSafe's hosted Jev, a hosted open server, or
   a self-hosted OpenJev by changing environment variables. This lowers vendor lock-in risk.
4. **Security checks run as code.** The 56-test suite covers prompt injection, poisoned documents and hostile model output, so a
   regression is caught in seconds instead of in a manual review. [MEASURE: your baseline for manual security review.]
5. **Explainable by default.** Every case carries weighted evidence, cited sources, an audit trail and a human decision, so
   reviewers do not rebuild the reasoning themselves.
6. **Reachable from developer tools.** The MCP server lets assistants in an IDE or chat investigate cases, with no approve tool.

**Business productivity (analyst and engineer time).** Per case: [MEASURE: median minutes with the tool vs without, n cases].
The built-in metric uses assumed baselines (45 and 90 minutes); do not present those as measured results.

**How to measure honestly (30 minutes).** Have 2 or 3 analysts or engineers handle the same 5 demo cases manually, then with
the console. Record start and end times, take the median per case, and state the sample size and that data is synthetic.

**Limits to state up front.** Synthetic data. Scores are rule-based and untuned. Model second opinions are advisory and unvalidated
on real data. No production deployment yet.
