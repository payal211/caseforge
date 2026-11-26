import { useState } from "react";

export const LABEL = {
  pending_approval: "Awaiting approval",
  approved: "Recommendation accepted",
  rejected: "Recommendation rejected",
  overridden: "Reviewer override",
};
const TAB = { bfsi: "Banking", claims: "Insurance", manufacturing: "Maintenance" };

export default function Sidebar({ domains, cur, setCur, cases, attacks, onInvestigate, onOpen, onAttack }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState("");
  const domain = domains.find((d) => d.name === cur);
  const investigating = domain?.subjects.find((subject) => subject.subject_id === busy);

  const run = async (key, fn) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <aside>
      <div className="tabs" role="group" aria-label="Domain">
        {domains.map((d) => (
          <button key={d.name} aria-pressed={d.name === cur} onClick={() => setCur(d.name)}>
            {TAB[d.name] ?? d.name}
          </button>
        ))}
      </div>

      <h2>Cases to investigate</h2>
      {domain && (
        <section className="domain-guide">
          <h3>{domain.title}</h3>
          <p>{domain.description}</p>
          <p><b>Objective:</b> {domain.objective}</p>
        </section>
      )}
      {investigating && (
        <div className="investigation-progress" role="status" aria-live="polite">
          Investigating {investigating.subject_id}. The model and read-only agents can take tens of seconds; keep this page open.
        </div>
      )}
      {domain?.subjects.map((s) => {
        const existing = cases.find((c) => c.domain === cur && c.subject_id === s.subject_id);
        const guide = domain.scenarios?.find((scenario) => scenario.subject_id === s.subject_id);
        return (
          <div className="row" key={s.subject_id}>
            <div>
              {s.subject_id}
              <small>{guide ? `${guide.title}: ${guide.why}` : s.label}</small>
            </div>
            <button
              className={existing ? "" : "primary"}
              disabled={busy === s.subject_id}
              onClick={() => (existing ? onOpen(existing.case_id) : run(s.subject_id, () => onInvestigate(cur, s.subject_id)))}
            >
              {busy === s.subject_id ? "Investigating…" : existing ? "Open" : "Investigate"}
            </button>
          </div>
        );
      })}
      {err && <div className="err" role="alert">{err}</div>}

      <h2 style={{ marginTop: 22 }}>Case queue</h2>
      {cases.length ? (
        cases.map((c) => {
          const related = cases.filter((other) => other.domain === c.domain && other.subject_id === c.subject_id);
          const hasDecision = related.some((other) => other.decision);
          const isDuplicatePending = c.status === "pending_approval" && hasDecision;
          return (
            <div className="row" key={c.case_id}>
              <div>
                <a href="#" style={{ color: "var(--ink)" }} onClick={(e) => { e.preventDefault(); onOpen(c.case_id); }}>
                  {c.subject_id}
                </a>
                <small>{c.case_id} · risk {Math.round(c.risk_score)}</small>
                {isDuplicatePending && <small className="duplicate-warning">Another case for this transaction already has a human decision.</small>}
              </div>
              <span className={`pill ${c.status}`}>{LABEL[c.status]}</span>
            </div>
          );
        })
      ) : (
        <div className="chip">No cases yet.</div>
      )}

      <h2 style={{ marginTop: 22 }}>Attack demo</h2>
      <p className="chip" style={{ marginTop: 0 }}>Poison live data, then watch the guardrails hold.</p>
      {attacks.map((a) => (
        <div className="row" key={a.id}>
          <div>
            {a.title}
            <small>{a.description}</small>
          </div>
          <button disabled={busy === a.id} onClick={() => run(a.id, () => onAttack(a.id))}>
            {busy === a.id ? "Running…" : "Run"}
          </button>
        </div>
      ))}
    </aside>
  );
}
