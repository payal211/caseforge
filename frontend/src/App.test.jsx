import { describe, it, expect, vi, beforeEach } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import App from "./App.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const CASE = {
  case_id: "CASE-1", domain: "bfsi", subject_id: "TXN-9001", status: "pending_approval", risk_score: 100,
  score_breakdown: {
    formula: "min(100, sum of evidence points)", raw_total: 105, cap: 100,
    signals: [{ signal: "new_device", source: "device_signals", points: 20, detail: "Device DEV-X77 never seen" }],
    action_bands: [{ minimum: 70, recommendation: "Approve dispute as fraud" }],
  },
  recommended_action: "Approve dispute as fraud: block card and refund customer", summary: "Scored 100/100.",
  reasoning: [], evidence: [{ source: "device_signals", signal: "new_device", detail: "Device DEV-X77 never seen", weight: 20 }],
  citations: [], artifacts: { customer_notification_draft: "Dear Asha" }, llm_used: false, investigation_seconds: 0.1,
  guardrail_flags: [], second_opinion: null, decision: null,
  agent_run: {
    status: "completed", tool_calls: 1, steps_used: 2,
    workers: [{ name: "fraud_forensics", objective: "Corroborates transaction history.", status: "completed", tool_calls: 1 }],
    critic: { status: "passed", accepted: 1, rejected: 0 },
    notes: [{ worker: "fraud_forensics", text: "The device is new for this account.", evidence: ["T1"] }],
    trace: [{ worker: "fraud_forensics", step: 1, kind: "tool_call", id: "T1", tool: "get_evidence", ok: true, summary: "Device DEV-X77 never seen" }],
  },
};
let cases;
let customerDisputes;

beforeEach(() => {
  cases = [];
  customerDisputes = [];
  globalThis.window.confirm = () => true;
  globalThis.window.scrollTo = () => {};
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const m = opts.method || "GET";
    const ok = (j) => ({ ok: true, json: async () => j });
    if (url === "/domains") return ok([{
      name: "bfsi", title: "Fraud", description: "Investigates disputed card transactions.",
      objective: "Help an analyst review cited evidence.", scenarios: [{
        subject_id: "TXN-9001", title: "High-risk cross-border dispute", why: "New device and unusual amount.",
      }], subjects: [{ subject_id: "TXN-9001", label: "ACC-1001 · 185000" }],
    }]);
    if (url === "/demo/attacks") return ok([]);
    if (url === "/metrics") return ok({ by_domain: {} });
    if (url === "/cx/assistant/sessions" && m === "POST") return ok({ session_id: "SESSION-1" });
    if (url === "/cx/accounts/ACC-1001/disputes") return ok(customerDisputes);
    if (url === "/cx/assistant/sessions/SESSION-1/messages" && m === "POST") {
      const { text } = JSON.parse(opts.body);
      if (text.includes("TXN-9001")) {
        cases = [CASE];
        customerDisputes = [{
          reference: "CASE-1", status: "under_review",
          customer_message: "Your dispute is still being reviewed.",
        }];
        return ok({
          reply: "The model may make an unsupported promise.",
          activities: ["open_dispute"],
          dispute_reference: "CASE-1",
          customer_message: "Your dispute is still being reviewed.",
        });
      }
      return ok({ reply: "I found your recent transactions.", activities: ["list_recent_transactions"] });
    }
    if (url === "/cases" && m === "GET") return ok(cases);
    if (url === "/cases" && m === "POST") { cases = [CASE]; return ok(CASE); }
    if (url === "/cases/CASE-1") return ok(CASE);
    if (url === "/cases/CASE-1/audit") return ok([{ event: "agent:gather", data: { seconds: 0.01 } }]);
    return { ok: false, statusText: "nope", json: async () => ({}) };
  });
});

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("console", () => {
  it("lists cases, investigates, and shows the case file with an approval panel", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    await act(async () => createRoot(el).render(<App />));
    await flush();
    expect(el.textContent).toContain("TXN-9001");
    expect(el.textContent).toContain("Objective:");
    expect(el.textContent).toContain("High-risk cross-border dispute");
    const btn = [...el.querySelectorAll("button")].find((b) => b.textContent === "Investigate");
    await act(async () => btn.click());
    await flush();
    expect(el.textContent).toContain("Recommended:");
    expect(el.textContent).toContain("105 raw points");
    expect(el.textContent).toContain("Device DEV-X77 never seen");
    expect(el.textContent).toContain("Approve recommendation");
    expect(el.textContent).toContain("Dear Asha");
    expect(el.textContent).toContain("Corroborates transaction history.");
    expect(el.textContent).toContain("Device DEV-X77 never seen");
    expect(el.textContent).toContain("not private model reasoning");
  });

  it("integrates the customer assistant into the app and sends chat messages", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    await act(async () => createRoot(el).render(<App />));
    await flush();
    customerDisputes = [{
      reference: "CASE-1", status: "not_approved",
      customer_message: "After review, we did not approve this dispute. Contact customer support.",
    }];
    const customerTab = [...el.querySelectorAll("button")].find((b) => b.textContent === "Customer agent");
    await act(async () => customerTab.click());
    await flush();
    expect(el.textContent).toContain("Card dispute assistant");
    expect(el.textContent).toContain("Asha Verma");
    expect(el.textContent).toContain("Your disputes");
    expect(el.textContent).toContain("not approved");
    expect(el.textContent).toContain("After review, we did not approve this dispute.");
    const input = el.querySelector('input[aria-label="Message the dispute assistant"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setValue.call(input, "I don't recognize a charge");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await flush();
    const form = el.querySelector(".chat-compose");
    await act(async () => form.requestSubmit());
    await flush();
    expect(el.textContent).toContain("I found your recent transactions.");
    expect(el.textContent).toContain("Looked up recent transactions");
    expect(el.textContent).toContain("GECX setup");
    expect(el.textContent).toContain("Check my dispute status");

    const disputeInput = el.querySelector('input[aria-label="Message the dispute assistant"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setValue.call(disputeInput, "I want to dispute TXN-9001");
      disputeInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await flush();
    await act(async () => el.querySelector(".chat-compose").requestSubmit());
    await flush();
    expect(el.textContent).toContain("Your dispute is still being reviewed.");
    expect(el.textContent).not.toContain("The model may make an unsupported promise.");
    expect(el.textContent).toContain("Opened or found an existing dispute");

    const analystTab = [...el.querySelectorAll("button")].find((b) => b.textContent === "Analyst console");
    await act(async () => analystTab.click());
    await flush();
    expect(el.textContent).toContain("CASE-1 · bfsi");
    expect(el.textContent).toContain("Approve recommendation");
  });
});
