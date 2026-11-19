import { describe, it, expect, vi, beforeEach } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import App from "./App.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const CASE = {
  case_id: "CASE-1", domain: "bfsi", subject_id: "TXN-9001", status: "pending_approval", risk_score: 100,
  recommended_action: "Approve dispute as fraud: block card and refund customer", summary: "Scored 100/100.",
  reasoning: [], evidence: [{ source: "device_signals", signal: "new_device", detail: "Device DEV-X77 never seen", weight: 20 }],
  citations: [], artifacts: { customer_notification_draft: "Dear Asha" }, llm_used: false, investigation_seconds: 0.1,
  guardrail_flags: [], second_opinion: null, decision: null,
};
let cases;

beforeEach(() => {
  cases = [];
  globalThis.window.confirm = () => true;
  globalThis.window.scrollTo = () => {};
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const m = opts.method || "GET";
    const ok = (j) => ({ ok: true, json: async () => j });
    if (url === "/domains") return ok([{ name: "bfsi", title: "Fraud", subjects: [{ subject_id: "TXN-9001", label: "ACC-1001 · 185000" }] }]);
    if (url === "/demo/attacks") return ok([]);
    if (url === "/metrics") return ok({ by_domain: {} });
    if (url === "/cx/assistant/sessions" && m === "POST") return ok({ session_id: "SESSION-1" });
    if (url === "/cx/assistant/sessions/SESSION-1/messages" && m === "POST") {
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
    const btn = [...el.querySelectorAll("button")].find((b) => b.textContent === "Investigate");
    await act(async () => btn.click());
    await flush();
    expect(el.textContent).toContain("Recommended:");
    expect(el.textContent).toContain("Device DEV-X77 never seen");
    expect(el.textContent).toContain("Approve recommendation");
    expect(el.textContent).toContain("Dear Asha");
  });

  it("integrates the customer assistant into the app and sends chat messages", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    await act(async () => createRoot(el).render(<App />));
    await flush();
    const customerTab = [...el.querySelectorAll("button")].find((b) => b.textContent === "Customer agent");
    await act(async () => customerTab.click());
    await flush();
    expect(el.textContent).toContain("Card dispute assistant");
    expect(el.textContent).toContain("Asha Verma");
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
  });
});
