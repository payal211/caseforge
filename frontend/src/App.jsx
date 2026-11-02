import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Sidebar from "./components/Sidebar.jsx";
import CaseView from "./components/CaseView.jsx";
import "./styles.css";

export default function App() {
  const [domains, setDomains] = useState([]);
  const [attacks, setAttacks] = useState([]);
  const [cur, setCur] = useState(null);
  const [cases, setCases] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [active, setActive] = useState(null); // { id, attack? }
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [c, m] = await Promise.all([api("/cases"), api("/metrics")]);
    setCases(c);
    setMetrics(m.by_domain || {});
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const d = await api("/domains");
        setDomains(d);
        setCur(d[0]?.name ?? null);
        setAttacks(await api("/demo/attacks"));
        await refresh();
      } catch (e) {
        setError(`Cannot reach the API: ${e.message}. Start it with: uvicorn caseforge.api.main:app`);
      }
    })();
  }, [refresh]);

  const investigate = async (domain, subject_id) => {
    const c = await api("/cases", "POST", { domain, subject_id });
    await refresh();
    setActive({ id: c.case_id });
  };
  const runAttack = async (id) => {
    const r = await api(`/demo/attacks/${id}`, "POST");
    await refresh();
    setActive({ id: r.case_id, attack: r });
  };
  const reset = async () => {
    if (!window.confirm("Clear all cases and the audit log?")) return;
    await api("/demo/reset", "DELETE");
    setActive(null);
    await refresh();
  };

  return (
    <>
      <header>
        <h1>CaseForge approval console</h1>
        <div className="chip">
          {Object.keys(metrics).length
            ? Object.entries(metrics).map(([n, d], i) => (
                <span key={n}>
                  {i > 0 && " | "}
                  <b>{n}</b>: {d.cases} case(s), agents {d.avg_agent_seconds}s, est. {d.est_reduction_pct}% faster
                  (assumed baseline {d.assumed_manual_minutes} min)
                </span>
              ))
            : "No cases run yet"}
        </div>
        <button onClick={reset}>Reset demo</button>
      </header>
      <main>
        <Sidebar
          domains={domains} cur={cur} setCur={setCur} cases={cases} attacks={attacks}
          activeId={active?.id} onInvestigate={investigate} onOpen={(id) => setActive({ id })} onAttack={runAttack}
        />
        <div>
          {error ? (
            <div className="err">{error}</div>
          ) : active ? (
            <CaseView key={active.id} id={active.id} attack={active.attack} onChanged={refresh} />
          ) : (
            <div className="empty">
              Pick a case on the left and select Investigate. The agents gather evidence, read policy, and write a
              case file for you to approve.
            </div>
          )}
        </div>
      </main>
    </>
  );
}
