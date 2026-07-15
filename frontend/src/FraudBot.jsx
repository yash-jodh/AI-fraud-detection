import { useState, useRef, useEffect, useCallback } from "react";

const GEMINI_URL =
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent";
const API = "http://localhost:8000";

const SYSTEM_PROMPT = `You are a fraud detection monitoring assistant embedded in a real-time fraud detection dashboard. The dashboard runs two ML models — Isolation Forest and a neural Autoencoder — plus a sliding-window drift detector, all backed by PostgreSQL for persistent history.

You receive live dashboard data with every user message. Use it to give specific, data-driven answers. Be concise. Use bullet points for lists. When values are unavailable (e.g. no transactions yet), say so and suggest starting the stream.`;

const SUGGESTIONS = [
  "Summarise what's happening right now",
  "What is the current fraud alert rate?",
  "Which model is flagging more transactions?",
  "Is there data drift detected?",
  "Show me the most suspicious recent transactions",
  "What does the drift mean for model accuracy?",
  "How are the two models different?",
  "Should I be worried about anything?",
];

async function fetchContext(authToken) {
  try {
    const headers = { Authorization: `Bearer ${authToken}` };
    const [histRes, driftRes, metricsRes] = await Promise.all([
      fetch(`${API}/history`, { headers }).catch(() => null),
      fetch(`${API}/drift-status`, { headers }).catch(() => null),
      fetch(`${API}/model-comparison`, { headers }).catch(() => null),
    ]);

    if (!histRes?.ok) return "⚠ FastAPI server is not reachable. Make sure it is running on port 8000.";

    const history = await histRes.json();
    const drift   = await driftRes.json().catch(() => ({}));
    const metrics = await metricsRes.json().catch(() => ({}));

    const total      = history.length;
    const fraudCount = history.filter(t => t.is_fraud).length;
    const alertRate  = total > 0 ? (fraudCount / total * 100).toFixed(1) : "0.0";
    const highRisk   = history.filter(t => t.risk_level === "HIGH").slice(-5);
    const medRisk    = history.filter(t => t.risk_level === "MEDIUM").slice(-3);
    const lastTen    = history.slice(-10).map(t =>
      `${t.transaction_id}($${t.amount?.toFixed(0)}) IF=${t.if_score?.toFixed(3)} AE=${t.ae_score?.toFixed(4)} → ${t.risk_level}`
    ).join("\n  ");

    return `=== LIVE DASHBOARD STATUS (PostgreSQL) ===
Transactions processed : ${total}
Fraud alerts           : ${fraudCount}  (${alertRate}% alert rate)
High-risk transactions : ${highRisk.length}
Medium-risk            : ${medRisk.length}
Last 10 transactions:
  ${lastTen || "none yet"}

=== DRIFT DETECTION ===
Status      : ${drift.drift_detected ? "DRIFT DETECTED ⚠" : "Normal"}
Window size : ${drift.window_size ?? 0} transactions
Max Z-score : ${drift.max_z_score ?? 0}
Drifting features: ${drift.drifted_features?.map(f => `${f.feature} (z=${f.z_score})`).join(", ") || "none"}

=== MODEL TRAINING METRICS ===
Isolation Forest → PR-AUC: ${metrics.isolation_forest?.pr_auc ?? "?"}, ROC-AUC: ${metrics.isolation_forest?.roc_auc ?? "?"}, Precision: ${metrics.isolation_forest?.precision ?? "?"}, Recall: ${metrics.isolation_forest?.recall ?? "?"}
Autoencoder      → PR-AUC: ${metrics.autoencoder?.pr_auc ?? "?"},     ROC-AUC: ${metrics.autoencoder?.roc_auc ?? "?"},     Precision: ${metrics.autoencoder?.precision ?? "?"},     Recall: ${metrics.autoencoder?.recall ?? "?"}
AE decision threshold: ${metrics.autoencoder?.threshold ?? "?"}`;
  } catch {
    return "Dashboard data unavailable.";
  }
}

async function callGemini(apiKey, history) {
  const res = await fetch(`${GEMINI_URL}?key=${apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
      contents: history.map(m => ({
        role: m.role === "bot" ? "model" : "user",
        parts: [{ text: m.text }],
      })),
      generationConfig: { temperature: 0.3, maxOutputTokens: 600 },
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message ?? `Gemini error ${res.status}`);
  }
  const data = await res.json();
  return data.candidates[0].content.parts[0].text;
}

function Message({ msg }) {
  const isBot = msg.role === "bot";
  return (
    <div className={`flex ${isBot ? "justify-start" : "justify-end"}`}>
      {isBot && (
        <div className="w-7 h-7 rounded-full bg-accent-indigo flex items-center justify-center text-sm mr-2 shrink-0 self-end">🤖</div>
      )}
      <div className={`max-w-[76%] px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap ${
        isBot
          ? "bg-surface-base text-ink border border-border rounded-[18px_18px_18px_4px]"
          : "bg-accent-indigo text-white rounded-[18px_18px_4px_18px]"
      }`}>
        {msg.text}
      </div>
    </div>
  );
}

function TypingDot() {
  return (
    <div className="flex gap-2 items-center">
      <div className="w-7 h-7 rounded-full bg-accent-indigo flex items-center justify-center text-sm">🤖</div>
      <div className="bg-surface-base border border-border rounded-[18px_18px_18px_4px] px-4 py-3 flex gap-1.5 items-center">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-ink-muted inline-block animate-bounce-dot"
            style={{ animationDelay: `${i * 0.2}s` }}
          />
        ))}
      </div>
    </div>
  );
}

export default function FraudBot({ apiKey, authToken }) {
  const INIT = [{
    role: "bot",
    text: "Hi! I'm your fraud monitoring assistant 👋\n\nI have access to your live dashboard data — transaction counts, fraud alerts, model metrics, drift status, and recent high-risk transactions, all backed by PostgreSQL.\n\nAsk me anything, or tap a suggestion below.",
  }];

  const [messages, setMessages] = useState(INIT);
  const [input,    setInput]    = useState("");
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = useCallback(async (text) => {
    const q = (text ?? input).trim();
    if (!q || loading) return;
    if (!apiKey) { setError("Paste your Gemini API key in the header first."); return; }

    setError("");
    setInput("");

    const context   = await fetchContext(authToken);
    const userMsg   = { role: "user", text: q };
    const ctxMsg    = { role: "user", text: `[LIVE DASHBOARD DATA]\n${context}\n\n[USER QUESTION]\n${q}` };

    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const history = [...messages, ctxMsg];
      const reply   = await callGemini(apiKey, history);
      setMessages(prev => [...prev, { role: "bot", text: reply }]);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [input, loading, apiKey, messages]);

  const clear = () => { setMessages(INIT); setError(""); };

  return (
    <div className="px-6 py-5 max-w-[860px] mx-auto">

      {/* Chat card */}
      <div className="bg-surface-card border border-border rounded-xl overflow-hidden mb-3.5">
        {/* Header */}
        <div className="px-4.5 py-3.5 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-full bg-accent-indigo flex items-center justify-center text-lg">🤖</div>
            <div>
              <div className="font-semibold text-sm">Fraud Monitor Bot</div>
              <div className="text-[11px] text-ink-muted">
                Powered by Gemini 3.5 Flash · reads live PostgreSQL-backed data on every message
              </div>
            </div>
          </div>
          <button
            onClick={clear}
            className="bg-transparent border border-border rounded-md text-ink-muted text-[11px] px-2.5 py-1 cursor-pointer"
          >Clear chat</button>
        </div>

        {/* Messages */}
        <div className="h-[440px] overflow-y-auto px-4.5 py-4.5 flex flex-col gap-3.5">
          {messages.map((msg, i) => <Message key={i} msg={msg} />)}
          {loading && <TypingDot />}
          {error && (
            <div className="bg-red-500/[0.08] border border-red-500/30 rounded-lg px-3.5 py-2.5 text-[13px] text-risk-high">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-3.5 py-3 border-t border-border flex gap-2 items-center">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Ask about fraud rates, drift, models, recent alerts…"
            disabled={loading}
            className="flex-1 bg-surface-base border border-border text-ink rounded-lg px-3.5 py-2 text-[13px]"
          />
          <button
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="bg-accent-indigo text-white border-none rounded-lg px-5 py-2 text-[13px] font-medium cursor-pointer disabled:opacity-50"
          >Send</button>
        </div>
      </div>

      {/* Suggestion chips */}
      <div className="text-xs text-ink-muted mb-2">
        Suggested questions
      </div>
      <div className="flex gap-2 flex-wrap">
        {SUGGESTIONS.map(s => (
          <button
            key={s}
            onClick={() => send(s)}
            disabled={loading}
            className="bg-surface-card border border-border text-ink rounded-full px-3.5 py-1.5 text-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >{s}</button>
        ))}
      </div>
    </div>
  );
}
