import { useState } from "react";

export const LABEL = { pending_approval: "Awaiting approval", approved: "Approved", rejected: "Rejected", overridden: "Overridden" };
const TAB = { bfsi: "Fraud", manufacturing: "Maintenance" };

export default function Sidebar({ domains, cur, setCur, cases, attacks, onInvestigate, onOpen, onAttack }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState("");
  const domain = domains.find((d) => d.name === cur);

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
      {domain?.subjects.map((s) => {
        const existing = cases.find((c) => c.domain === cur && c.subject_id === s.subject_id);
        return (
          <div className="row" key={s.subject_id}>
            <div>
              {s.subject_id}
              <small>{s.label}</small>
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
      {err && <div className="err">{err}</div>}

      <h2 style={{ marginTop: 22 }}>Case queue</h2>
      {cases.length ? (
        cases.map((c) => (
          <div className="row" key={c.case_id}>
            <div>
              <a href="#" style={{ color: "var(--ink)" }} onClick={(e) => { e.preventDefault(); onOpen(c.case_id); }}>
                {c.subject_id}
              </a>
              <small>risk {Math.round(c.risk_score)}</small>
            </div>
            <span className={`pill ${c.status}`}>{LABEL[c.status]}</span>
          </div>
        ))
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
