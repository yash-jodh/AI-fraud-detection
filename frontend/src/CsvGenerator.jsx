import { useState } from "react";

const GEMINI_URL =
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent";

const SCENARIOS = [
  { value: "mixed",            label: "Mixed fraud types" },
  { value: "card_not_present", label: "Card-not-present fraud" },
  { value: "account_takeover", label: "Account takeover" },
  { value: "identity_theft",   label: "Identity theft" },
  { value: "phishing",         label: "Phishing attack" },
  { value: "synthetic",        label: "Synthetic identity" },
  { value: "friendly_fraud",   label: "Friendly fraud / chargeback" },
];

async function callGemini(apiKey, prompt) {
  const res = await fetch(`${GEMINI_URL}?key=${apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.85, maxOutputTokens: 4096 },
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message ?? `Gemini error ${res.status}`);
  }
  const data = await res.json();
  return data.candidates[0].content.parts[0].text;
}

function parseCSV(raw) {
  const cleaned = raw.replace(/```[\w]*/g, "").replace(/```/g, "").trim();
  const lines   = cleaned.split("\n").filter(l => l.trim().length > 0);
  if (lines.length < 2) return { headers: [], rows: [], raw: cleaned };

  const headers = lines[0].split(",").map(h => h.trim().replace(/^"|"$/g, ""));

  const rows = lines.slice(1).map(line => {
    const cols = [];
    let cur = "", inQ = false;
    for (const ch of line) {
      if (ch === '"') { inQ = !inQ; continue; }
      if (ch === "," && !inQ) { cols.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    cols.push(cur.trim());
    return cols;
  });

  return { headers, rows, raw: cleaned };
}

function Badge({ text, positive }) {
  const cls =
    positive === true  ? "bg-green-500/15 text-risk-low"  :
    positive === false ? "bg-red-500/15 text-risk-high"   :
    "bg-amber-500/15 text-risk-medium";
  return (
    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-md ${cls}`}>{text}</span>
  );
}

export default function CsvGenerator({ apiKey }) {
  const [scenario, setScenario] = useState("mixed");
  const [count,    setCount]    = useState(20);
  const [custom,   setCustom]   = useState("");
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");
  const [result,   setResult]   = useState(null);

  const generate = async () => {
    if (!apiKey) { setError("Paste your Gemini API key in the header first."); return; }
    setLoading(true); setError(""); setResult(null);

    const label = SCENARIOS.find(s => s.value === scenario)?.label ?? scenario;
    const extra = custom ? `\nExtra context: ${custom}` : "";

    const prompt = `Generate a CSV dataset with exactly ${count} rows of realistic CRM fraud investigation call records for a bank fraud team.

Use EXACTLY these column headers (one header row, then ${count} data rows):
call_id,customer_name,phone,email,account_id,transaction_amount,merchant,fraud_type,risk_score,call_notes,agent_id,call_date,resolution,is_confirmed_fraud

Column rules:
- call_id: CALL-0001 … CALL-${String(count).padStart(4, "0")}
- customer_name: realistic full names
- phone: 555-XXX-XXXX format
- email: realistic, matching the customer name
- account_id: ACC-XXXXX (5 digit)
- transaction_amount: number, no currency symbol, range 50-12000
- merchant: realistic company name
- fraud_type: one of card_not_present / account_takeover / identity_theft / friendly_fraud / phishing / synthetic_identity
- risk_score: decimal 0.00–1.00 (>0.7 for confirmed fraud)
- call_notes: one realistic sentence with NO commas (use semicolons instead)
- agent_id: AGT-XX
- call_date: 2024-MM-DD HH:MM:SS
- resolution: pending / disputed / confirmed_fraud / cleared
- is_confirmed_fraud: YES or NO
- Scenario: ${label}${extra}

CRITICAL: Return ONLY raw CSV. First line = headers. No markdown fences, no blank lines, no commentary.`;

    try {
      const raw  = await callGemini(apiKey, prompt);
      const data = parseCSV(raw);
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const download = () => {
    if (!result) return;
    const blob = new Blob([result.raw], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement("a"), {
      href: url, download: `fraud_crm_${scenario}_${count}rows.csv`,
    });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="px-6 py-5 max-w-[1400px] mx-auto">

      {/* Controls card */}
      <div className="bg-surface-card border border-border rounded-xl p-5 mb-4">
        <div className="font-semibold text-[15px] mb-1">
          CRM Fraud Call Generator
        </div>
        <div className="text-xs text-ink-muted mb-5">
          Gemini AI writes realistic bank fraud investigation call records — great for demos, testing, and pipeline seeding.
        </div>

        <div className="flex gap-3 flex-wrap items-end">
          <div className="flex-[2] min-w-[180px]">
            <label className="text-xs text-ink-muted block mb-1.5">Fraud scenario</label>
            <select
              value={scenario}
              onChange={e => setScenario(e.target.value)}
              className="w-full bg-surface-base border border-border text-ink rounded-lg px-3 py-2 text-[13px]"
            >
              {SCENARIOS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>

          <div className="min-w-[90px]">
            <label className="text-xs text-ink-muted block mb-1.5">Records (5–100)</label>
            <input
              type="number" min={5} max={100} value={count}
              onChange={e => setCount(Number(e.target.value))}
              className="w-full bg-surface-base border border-border text-ink rounded-lg px-3 py-2 text-[13px]"
            />
          </div>

          <div className="flex-[3] min-w-[200px]">
            <label className="text-xs text-ink-muted block mb-1.5">Extra instructions (optional)</label>
            <input
              type="text" value={custom}
              placeholder="e.g. elderly victims, international cards, high-value transfers"
              onChange={e => setCustom(e.target.value)}
              className="w-full bg-surface-base border border-border text-ink rounded-lg px-3 py-2 text-[13px]"
            />
          </div>

          <button
            onClick={generate} disabled={loading}
            className="bg-accent-indigo text-white border-none rounded-lg px-5 py-2 text-[13px] font-medium cursor-pointer whitespace-nowrap disabled:opacity-60"
          >
            {loading ? "Generating…" : "✦ Generate CSV"}
          </button>

          {result && (
            <button
              onClick={download}
              className="bg-surface-base text-ink border border-border rounded-lg px-5 py-2 text-[13px] font-medium cursor-pointer whitespace-nowrap"
            >↓ Download</button>
          )}
        </div>

        {error && (
          <div className="mt-3 text-risk-high text-[13px]">{error}</div>
        )}
      </div>

      {/* Empty / loading state */}
      {!result && (
        <div className="bg-surface-card border border-border rounded-xl text-center py-14 px-6 text-ink-muted text-[13px]">
          {loading
            ? `Gemini is writing ${count} fraud call records…`
            : "Configure options above and click Generate CSV"}
        </div>
      )}

      {/* Results table */}
      {result && result.headers.length > 0 && (
        <div className="bg-surface-card border border-border rounded-xl p-5 overflow-x-auto">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-medium text-sm">
                {result.rows.length} records generated
              </div>
              <div className="text-xs text-ink-muted mt-0.5">
                {result.rows.filter(r => r[13] === "YES").length} confirmed fraud ·{" "}
                {result.rows.filter(r => r[12] === "pending").length} pending resolution
              </div>
            </div>
          </div>

          <table className="border-collapse text-xs min-w-full">
            <thead>
              <tr className="border-b border-border">
                {result.headers.map((h, i) => (
                  <th key={i} className="px-2.5 py-2 text-left whitespace-nowrap font-medium text-ink-muted text-[11px] uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, ri) => (
                <tr key={ri} className={`border-b border-border ${row[13] === "YES" ? "bg-red-500/[0.04]" : ""}`}>
                  {result.headers.map((h, ci) => {
                    const val = row[ci] ?? "";
                    let cell  = val;

                    if (h === "is_confirmed_fraud")
                      cell = <Badge text={val} positive={val === "NO"} />;
                    else if (h === "resolution")
                      cell = <Badge
                        text={val}
                        positive={val === "cleared" ? true : val === "confirmed_fraud" ? false : undefined}
                      />;
                    else if (h === "risk_score")
                      cell = <span className={`font-medium ${parseFloat(val) > 0.7 ? "text-risk-high" : parseFloat(val) > 0.4 ? "text-risk-medium" : "text-risk-low"}`}>{val}</span>;

                    return (
                      <td
                        key={ci}
                        className={`px-2.5 py-2 text-ink ${h === "call_notes" ? "whitespace-normal max-w-[260px]" : "whitespace-nowrap"} ${ci === 0 ? "font-medium" : "font-normal"}`}
                      >{cell}</td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
