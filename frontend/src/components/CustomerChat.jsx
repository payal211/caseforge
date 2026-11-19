import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const CUSTOMERS = [
  { accountId: "ACC-1001", name: "Asha Verma" },
  { accountId: "ACC-1002", name: "Rohan Mehta" },
];

const ACTIVITY_LABELS = {
  list_recent_transactions: "Looked up recent transactions",
  open_dispute: "Opened a dispute for analyst review",
  check_dispute_status: "Checked dispute status",
};

export default function CustomerChat({ onActivity }) {
  const [customer, setCustomer] = useState(CUSTOMERS[0]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  const startSession = async (selected) => {
    setBusy(true);
    setError("");
    setMessages([]);
    setSessionId("");
    try {
      const session = await api("/cx/assistant/sessions", "POST", { account_id: selected.accountId });
      setSessionId(session.session_id);
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

  const changeCustomer = (event) => {
    const selected = CUSTOMERS.find((item) => item.accountId === event.target.value);
    if (!selected) return;
    setCustomer(selected);
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
        text: result.reply,
        activities: result.activities ?? [],
      }]);
      if (result.activities?.includes("open_dispute")) await onActivity();
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
