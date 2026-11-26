import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

const CUSTOMERS = [
  { accountId: "ACC-1001", name: "Asha Verma" },
  { accountId: "ACC-1002", name: "Rohan Mehta" },
];

const ACTIVITY_LABELS = {
  list_recent_transactions: "Looked up recent transactions",
  open_dispute: "Opened or found an existing dispute",
  check_dispute_status: "Checked dispute status",
};

export default function CustomerChat({ onActivity }) {
  const [customer, setCustomer] = useState(CUSTOMERS[0]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [disputes, setDisputes] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const accountRef = useRef(customer.accountId);

  const loadDisputes = useCallback(async (accountId = customer.accountId) => {
    try {
      const currentDisputes = await api(`/cx/accounts/${accountId}/disputes`);
      if (accountRef.current === accountId) setDisputes(currentDisputes);
      return currentDisputes;
    } catch (e) {
      if (accountRef.current === accountId) setError(e.message);
      return [];
    }
  }, [customer.accountId]);

  const startSession = async (selected) => {
    setBusy(true);
    setError("");
    setMessages([]);
    setSessionId("");
    try {
      const session = await api("/cx/assistant/sessions", "POST", { account_id: selected.accountId });
      setSessionId(session.session_id);
      await loadDisputes(selected.accountId);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  useEffect(() => {
    startSession(customer);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => loadDisputes(), 5000);
    return () => window.clearInterval(timer);
  }, [loadDisputes]);

  const changeCustomer = (event) => {
    const selected = CUSTOMERS.find((item) => item.accountId === event.target.value);
    if (!selected) return;
    accountRef.current = selected.accountId;
    setCustomer(selected);
    setDisputes([]);
    startSession(selected);
  };

  const send = async (event) => {
    event.preventDefault();
    const message = text.trim();
    if (!message || !sessionId || busy) return;
    setText("");
    setError("");
    setMessages((items) => [...items, { role: "customer", text: message }]);
    setBusy(true);
    try {
      const result = await api(`/cx/assistant/sessions/${sessionId}/messages`, "POST", { text: message });
      setMessages((items) => [...items, {
        role: "assistant",
        text: result.customer_message || result.reply,
        activities: result.activities ?? [],
      }]);
      const currentDisputes = await loadDisputes();
      const caseActivity = (result.activities ?? []).some((activity) =>
        activity === "open_dispute" || activity === "check_dispute_status");
      if (caseActivity) await onActivity(result.dispute_reference || currentDisputes[0]?.reference);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  return (
    <section className="customer-demo">
      <div className="customer-heading">
        <div>
          <div className="eyebrow">CUSTOMER EXPERIENCE · LOCAL DEMO</div>
          <h2>Card dispute assistant</h2>
          <p>Ask about a transaction, open a dispute, or check its status.</p>
        </div>
        <label className="customer-picker">
          Demo customer
          <select value={customer.accountId} onChange={changeCustomer} disabled={busy}>
            {CUSTOMERS.map((item) => (
              <option key={item.accountId} value={item.accountId}>
                {item.name} · {item.accountId}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="demo-notice">
        Demo only: the customer selector represents a signed-in identity. It is not authentication.
        Disputes remain pending until an analyst makes a decision in the analyst console.
      </div>

      <details className="customer-setup">
        <summary>GECX setup</summary>
        <p>This browser chat uses the Google ADK customer agent configured on the CaseForge API. Set the model before starting or restarting the API in Windows Command Prompt.</p>
        <ol>
          <li>Start Ollama and confirm the model supports tools: <code>ollama show llama3.1:latest</code>.</li>
          <li>Set the GECX chat model and the separate CaseForge investigation model, then start the API:</li>
        </ol>
        <pre>{'set "GECX_PROVIDER=ollama"\nset "GECX_MODEL=llama3.1:latest"\nset "OLLAMA_MODEL=llama3.1:latest"\nuvicorn caseforge.api.main:app --reload'}</pre>
        <p>For Gemini, set <code>GECX_PROVIDER=gemini</code> and <code>GOOGLE_API_KEY</code>. The full guide is in <code>gecx/README.md</code>.</p>
      </details>

      <section className="customer-disputes" aria-label="Your disputes">
        <h3>Your disputes</h3>
        {!disputes.length ? <p>No disputes yet.</p> : disputes.map((dispute) => (
          <article className="customer-dispute" key={dispute.reference}>
            <div><b>{dispute.reference}</b> <span className="pill">{dispute.status.replaceAll("_", " ")}</span></div>
            <p>{dispute.customer_message}</p>
          </article>
        ))}
      </section>

      <div className="quick-prompts">
        <b>Try asking:</b>
        <button type="button" disabled={busy} onClick={() => setText("I don't recognize a charge.")}>
          I don't recognize a charge
        </button>
        <button type="button" disabled={busy} onClick={() => setText("Show my recent transactions.")}>
          Show my recent transactions
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setText(`I want to dispute ${customer.accountId === "ACC-1001" ? "TXN-9001" : "TXN-9002"}; I don't recognize this purchase.`)}
        >
          Dispute a sample transaction
        </button>
        <button type="button" disabled={busy} onClick={() => setText("Can I get an update on my dispute?")}>
          Check my dispute status
        </button>
      </div>

      <div className="chat-transcript" aria-live="polite">
        {!messages.length && !busy && (
          <div className="chat-welcome">
            <strong>Hello, {customer.name}.</strong>
            <span>Tell me what you need help with. For example: “I don't recognize a charge.”</span>
          </div>
        )}
        {messages.map((message, index) => (
          <div className={`chat-message ${message.role}`} key={`${index}-${message.role}`}>
            <span className="message-author">{message.role === "customer" ? customer.name : "CaseForge assistant"}</span>
            <p>{message.text}</p>
            {!!message.activities?.length && (
              <div className="chat-activities">
                {message.activities.map((activity, activityIndex) => (
                  <span key={`${activity}-${activityIndex}`}>
                    {ACTIVITY_LABELS[activity] ?? "Used a CaseForge service"}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="chat-thinking">The assistant is responding…</div>}
      </div>

      {error && <div className="err" role="alert">{error}</div>}
      <form className="chat-compose" onSubmit={send}>
        <input
          ref={inputRef}
          aria-label="Message the dispute assistant"
          placeholder="Write a message…"
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={2000}
          disabled={!sessionId || busy}
        />
        <button className="primary" type="submit" disabled={!sessionId || !text.trim() || busy}>
          Send
        </button>
      </form>
      <p className="chat-footnote">
        The assistant can open and track disputes, but only a human analyst can approve or reject one.
      </p>
    </section>
  );
}
