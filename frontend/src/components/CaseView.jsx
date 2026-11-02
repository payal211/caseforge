import { useEffect, useState } from "react";
import { api } from "../api";
import { LABEL } from "./Sidebar.jsx";

const col = (s) => (s >= 70 ? "var(--hi)" : s >= 40 ? "var(--mid)" : "var(--lo)");
const Card = ({ title, style, children }) => (
  <section className="card" style={style}>
    {title && <h2>{title}</h2>}
    {children}
  </section>
);

function AttackBanner({ r }) {
  const ok = r.same_decision && r.flags.length > 0;
  return (
    <Card title={`Attack: ${r.title}`} style={{ borderColor: ok ? "var(--lo)" : "var(--hi)" }}>
      <p className="chip" style={{ marginTop: 0 }}>Injected text</p>
      <pre>{r.payload}</pre>
      <table>
        <tbody>
          <tr><th></th><th>Clean run</th><th>Under attack</th></tr>
          <tr><th>Risk score</th><td>{Math.round(r.clean.risk_score)}</td><td>{Math.round(r.attacked.risk_score)}</td></tr>
          <tr><th>Action</th><td>{r.clean.recommended_action}</td><td>{r.attacked.recommended_action}</td></tr>
        </tbody>
      </table>
      <p style={{ margin: "10px 0 0" }}>
        <b>
          {ok
            ? "Attack contained: the decision did not change, the case is flagged, and a human still has to approve."
            : "Check the result below: the guardrails did not fully contain this attack."}
        </b>
      </p>
    </Card>
  );
}

function WorkOrder({ wo, parts }) {
  return (
    <Card title="Draft work order">
      <table>
        <tbody>
          <tr><th>Machine</th><td>{wo.machine}</td><th>Priority</th><td>{wo.priority}</td></tr>
          <tr><th>Cause</th><td>{wo.suspected_cause}</td><th>Downtime</th><td>{wo.estimated_downtime_hours} h</td></tr>
        </tbody>
      </table>
      <p><b>Tasks</b></p>
      <ol>{wo.tasks.map((t, i) => <li key={i}>{t}</li>)}</ol>
      <p><b>Parts request</b></p>
      <table>
        <tbody>
          {parts.map((p) => (
            <tr key={p.part_no}><td className="mono">{p.part_no}</td><td>{p.description}</td><td>× {p.qty}</td></tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function DecisionPanel({ c, onDecided }) {
  const [reviewer, setReviewer] = useState("analyst");
  const [note, setNote] = useState("");
  const [override, setOverride] = useState("");
  const [showOverride, setShowOverride] = useState(false);
  const [err, setErr] = useState("");
  const d = c.decision;

  if (d) {
    const color = d.outcome === "approve" ? "var(--lo)" : d.outcome === "reject" ? "var(--hi)" : "var(--acc)";
    return (
      <Card title="Decision">
        <div className="stamp" style={{ color }}>{LABEL[c.status]}</div>
        <p style={{ margin: 0 }}>
          <b>{d.reviewer}</b>: {d.final_action}
          {d.note && <><br /><span className="chip">Note: {d.note}</span></>}
        </p>
      </Card>
    );
  }
  const decide = async (outcome) => {
    if (outcome === "override" && !showOverride) return setShowOverride(true);
    try {
      await api(`/cases/${c.case_id}/decision`, "POST", {
        reviewer: reviewer || "analyst", outcome, note, override_action: override || null,
      });
      await onDecided();
    } catch (e) {
      setErr(e.message);
    }
  };
  return (
    <Card title="Decision">
      <div className="decide">
        <input aria-label="Reviewer name" placeholder="Your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <input aria-label="Note" placeholder="Note for the audit log (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        {showOverride && (
          <input autoFocus aria-label="Override action" placeholder="Override: type the action you want instead"
                 value={override} onChange={(e) => setOverride(e.target.value)} />
        )}
        <div className="btns">
          <button className="primary" onClick={() => decide("approve")}>Approve recommendation</button>
          <button className="danger" onClick={() => decide("reject")}>Reject</button>
          <button onClick={() => decide("override")}>Override…</button>
        </div>
        {err && <div className="err">{err}</div>}
      </div>
    </Card>
  );
}

export default function CaseView({ id, attack, onChanged }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const [c, audit] = await Promise.all([api(`/cases/${id}`), api(`/cases/${id}/audit`)]);
      setData({ c, steps: audit.filter((x) => x.event.startsWith("agent:")) });
    } catch (e) {
      setErr(e.message);
    }
  };
  useEffect(() => { load(); window.scrollTo?.(0, 0); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <div className="err">{err}</div>;
  if (!data) return <div className="empty">Loading…</div>;
  const { c, steps } = data;
  const art = c.artifacts || {};
  const so = c.second_opinion;

  return (
    <>
      {attack && <AttackBanner r={attack} />}
      <Card>
        <div className="row" style={{ border: 0, paddingTop: 0 }}>
          <div>
            <h2 style={{ margin: 0 }}>{c.subject_id}</h2>
            <small className="chip">{c.case_id} · {c.domain}</small>
          </div>
          <span className={`pill ${c.status}`}>{LABEL[c.status]}</span>
        </div>
        <div className="score">
          <div className="num" style={{ color: col(c.risk_score) }}>{Math.round(c.risk_score)}</div>
          <div style={{ flex: 1 }}>
            <div className="meter"><i style={{ width: `${c.risk_score}%`, background: col(c.risk_score) }} /></div>
            <p style={{ margin: "8px 0 0" }}><b>Recommended:</b> {c.recommended_action}</p>
          </div>
        </div>
      </Card>

      <Card title="Why">
        <p style={{ marginTop: 0 }}>{c.summary}</p>
        <span className="chip">
          {c.llm_used ? "Narrative written by the local model" : "Rule-based narrative (no model reached)"} · {c.investigation_seconds}s
        </span>
      </Card>

      {so?.available && (
        <Card title="Second opinion">
          <p style={{ margin: 0 }}>
            {so.question}<br />
            <b>Model says yes with probability {so.p_yes}</b> ({so.model}).{" "}
            {so.disagrees ? `${so.note}. Look closely before approving.` : "Consistent with the rules-based result."}{" "}
            <span className="chip">Advisory only.</span>
          </p>
        </Card>
      )}

      {c.agent_run && (
        <Card title="Agent investigation (advisory)">
          <p style={{ marginTop: 0 }}>
            <span className="pill">{c.agent_run.status}</span>{" "}
            <span className="chip">{c.agent_run.tool_calls} tool call(s), {c.agent_run.steps_used} step(s). Read-only tools; cannot change the score or approve.</span>
          </p>
          {c.agent_run.notes.length ? (
            <ul>{c.agent_run.notes.map((n, i) => <li key={i}>{n.text} <span className="chip mono">[{n.evidence.join(", ")}]</span></li>)}</ul>
          ) : <p className="chip">No grounded notes were produced.</p>}
          <details>
            <summary>Agent trace</summary>
            {c.agent_run.trace.map((t, i) => (
              <div className="chip mono" key={i}>{t.step}. {t.kind}{t.tool ? ` ${t.tool}` : ""}{t.redactions ? ` (${t.redactions} redaction(s))` : ""}</div>
            ))}
          </details>
        </Card>
      )}

      {c.guardrail_flags?.length > 0 && (
        <Card title="Guardrail alert" style={{ borderColor: "var(--mid)" }}>
          <p style={{ marginTop: 0 }}>Suspicious or untrusted content was found and removed. It did not change the score or action.</p>
          <ul>{c.guardrail_flags.map((f) => <li className="mono" key={f}>{f}</li>)}</ul>
        </Card>
      )}

      <Card title="Evidence">
        {c.evidence.map((e, i) => (
          <div className={`ev ${e.weight ? "" : "zero"}`} key={i}>
            <div>{e.detail}<br /><span className="chip mono">{e.source}</span></div>
            <div className="bar" title={`weight ${e.weight}`}><i style={{ width: `${Math.min(100, (e.weight * 100) / 35)}%` }} /></div>
          </div>
        ))}
      </Card>

      <Card title="Sources cited">
        {c.citations.length ? c.citations.map((x) => (
          <details key={`${x.doc}/${x.section}`}>
            <summary>{x.doc} / {x.section}</summary>
            <pre>{x.excerpt}</pre>
          </details>
        )) : "None"}
      </Card>

      {art.work_order && <WorkOrder wo={art.work_order} parts={art.parts_request || []} />}
      {art.customer_notification_draft && (
        <Card title="Draft customer message"><p style={{ margin: 0 }}>{art.customer_notification_draft}</p></Card>
      )}

      <Card title="Agent trace">
        <div className="trace">{steps.map((s, i) => <span key={i}>{s.event.slice(6)} · {s.data.seconds}s</span>)}</div>
      </Card>

      <DecisionPanel c={c} onDecided={async () => { await load(); await onChanged(); }} />
    </>
  );
}
