import { useState, useEffect, useRef, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from "recharts";
import CsvGenerator from "./CsvGenerator";
import FraudBot     from "./FraudBot";
import Login        from "./Login";

const API  = "http://localhost:8000";
const WS   = "ws://localhost:8000/ws";
const MAX_CHART  = 100;
const MAX_ALERTS = 25;

// -- shared components --

function Card({ children, className = "" }) {
  return (
    <div className={`bg-surface-card border border-border rounded-xl p-5 ${className}`}>
      {children}
    </div>
  );
}

function CardTitle({ children, sub }) {
  return (
    <div className="mb-4">
      <div className="font-semibold text-[15px]">{children}</div>
      {sub && <div className="text-xs text-ink-muted mt-[3px]">{sub}</div>}
    </div>
  );
}

function StatCard({ label, value, sub, colorClass, pulse }) {
  return (
    <Card className="flex-1 min-w-[140px] relative overflow-hidden">
      {pulse && (
        <span className={`absolute top-3.5 right-3.5 w-2 h-2 rounded-full animate-pulse-soft ${colorClass?.dot ?? "bg-risk-low"}`} />
      )}
      <div className="text-xs text-ink-muted mb-1.5">{label}</div>
      <div className={`text-[30px] font-bold leading-none ${colorClass?.text ?? "text-ink"}`}>{value}</div>
      {sub && <div className="text-[11px] text-ink-muted mt-1.5">{sub}</div>}
    </Card>
  );
}

function Badge({ children, className = "" }) {
  return (
    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-md whitespace-nowrap ${className || "bg-border text-ink"}`}>
      {children}
    </span>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-surface-base border border-border rounded-lg px-3.5 py-2.5 text-xs">
      <div className="text-ink-muted mb-1.5">{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="mb-0.5" style={{ color: p.stroke }}>
          {p.name}: <strong>{Number(p.value).toFixed(4)}</strong>
        </div>
      ))}
    </div>
  );
}

const LEVEL_CLASSES = {
  HIGH:   "text-red-300 bg-red-950",
  MEDIUM: "text-amber-200 bg-amber-950",
  LOW:    "text-green-300 bg-green-950",
};

const TABS = [
  { id: "dashboard", label: "🛡 Dashboard" },
  { id: "crm",       label: "📋 CRM Generator" },
  { id: "bot",       label: "🤖 Fraud Bot" },
];

// -- main app --

export default function App() {
  const [token,     setToken]     = useState(() => localStorage.getItem("fraud_token") || "");
  const [username,  setUsername]  = useState(() => localStorage.getItem("fraud_username") || "");
  const [tab,       setTab]       = useState("dashboard");
  const [apiKey,    setApiKey]    = useState("");
  const [showKey,   setShowKey]   = useState(false);

  const handleLogin = (newToken, user) => {
    localStorage.setItem("fraud_token", newToken);
    localStorage.setItem("fraud_username", user);
    setToken(newToken);
    setUsername(user);
  };

  const handleLogout = () => {
    localStorage.removeItem("fraud_token");
    localStorage.removeItem("fraud_username");
    setToken("");
    setUsername("");
  };

  // dashboard state
  const [chart,     setChart]     = useState([]);
  const [alerts,    setAlerts]    = useState([]);
  const [metrics,   setMetrics]   = useState(null);
  const [drift,     setDrift]     = useState(null);
  const [connected, setConnected] = useState(false);
  const [totals,    setTotals]    = useState({ sent: 0, fraud: 0 });
  const totRef = useRef({ sent: 0, fraud: 0 });
  const ws     = useRef(null);

  useEffect(() => {
    if (!token) return;
    const authHeaders = { Authorization: `Bearer ${token}` };

    fetch(`${API}/model-comparison`, { headers: authHeaders }).then(r => r.json()).then(setMetrics).catch(() => {});
    // Warm the dashboard from PostgreSQL-backed history on first load / refresh,
    // so a page reload doesn't lose everything until the next WS message.
    fetch(`${API}/history`, { headers: authHeaders }).then(r => r.json()).then(rows => {
      if (!Array.isArray(rows) || rows.length === 0) return;
      totRef.current = {
        sent: rows.length,
        fraud: rows.filter(r => r.is_fraud).length,
      };
      setTotals({ ...totRef.current });
      setChart(rows.slice(-MAX_CHART).map((r, i) => ({
        name: `#${i + 1}`,
        IF: parseFloat((r.if_score ?? 0).toFixed(4)),
        AE: parseFloat((r.ae_score ?? 0).toFixed(4)),
      })));
      setAlerts(rows.filter(r => r.is_fraud).slice(-MAX_ALERTS).reverse().map((r, i) => ({ ...r, seq: rows.length - i })));
    }).catch(() => {});
  }, [token]);

  const connect = useCallback(() => {
    if (!token) return;
    try { ws.current?.close(); } catch (_) {}
    // Native browser WebSockets can't send custom headers, so the JWT
    // travels as a query param instead — the backend reads it there.
    const sock = new WebSocket(`${WS}?token=${encodeURIComponent(token)}`);
    ws.current = sock;
    sock.onopen  = () => setConnected(true);
    sock.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
    sock.onerror = () => sock.close();
    sock.onmessage = (e) => {
      const d = JSON.parse(e.data);
      totRef.current.sent  += 1;
      if (d.is_fraud) totRef.current.fraud += 1;
      setTotals({ ...totRef.current });
      setChart(prev => [
        ...prev.slice(-(MAX_CHART - 1)),
        { name: `#${totRef.current.sent}`, IF: parseFloat(d.if_score?.toFixed(4) ?? 0), AE: parseFloat(d.ae_score?.toFixed(4) ?? 0) },
      ]);
      if (d.is_fraud) setAlerts(prev => [{ ...d, seq: totRef.current.sent }, ...prev.slice(0, MAX_ALERTS - 1)]);
      setDrift(d.drift ?? null);
    };
  }, [token]);

  useEffect(() => { connect(); return () => ws.current?.close(); }, [connect]);

  const alertRate  = totals.sent > 0 ? ((totals.fraud / totals.sent) * 100).toFixed(1) : "0.0";
  const driftIsOn  = drift?.drift_detected;

  if (!token) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <>
      {/* -- header -- */}
      <div className="bg-surface-card border-b border-border sticky top-0 z-10">
        {/* top bar */}
        <div className="px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <div className="font-bold text-base tracking-[-0.3px]">
              🛡 Fraud Detection System
            </div>
            <div className="text-[11px] text-ink-muted mt-px">
              Isolation Forest + Autoencoder + Gemini AI · PostgreSQL-backed
            </div>
          </div>

          {/* Gemini API key input */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-muted whitespace-nowrap">
              Gemini API key
            </span>
            <input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="AIza…"
              className="w-[200px] bg-surface-base border border-border text-ink rounded-lg px-2.5 py-1.5 text-xs"
            />
            <button
              onClick={() => setShowKey(s => !s)}
              className="bg-transparent border-none text-ink-muted cursor-pointer text-sm p-0.5"
              title={showKey ? "Hide" : "Show"}
            >{showKey ? "🙈" : "👁"}</button>
            <div className="flex items-center gap-1.5 text-xs ml-2">
              <span className={`w-[7px] h-[7px] rounded-full inline-block ${connected ? "bg-risk-low shadow-[0_0_0_3px_#22c55e33]" : "bg-risk-high"}`} />
              <span className={connected ? "text-risk-low" : "text-risk-high"}>
                {connected ? "Live" : "Reconnecting…"}
              </span>
            </div>

            <div className="flex items-center gap-2 ml-2 pl-3 border-l border-border">
              <span className="text-xs text-ink-muted">{username}</span>
              <button
                onClick={handleLogout}
                className="bg-transparent border border-border rounded-md text-ink-muted text-[11px] px-2.5 py-1 cursor-pointer"
              >Log out</button>
            </div>
          </div>
        </div>

        {/* tab bar */}
        <div className="flex px-6 gap-1">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`bg-transparent border-none cursor-pointer px-4 py-2.5 text-[13px] font-medium -mb-px transition-colors border-b-2 ${
                tab === t.id ? "text-accent-indigo border-accent-indigo" : "text-ink-muted border-transparent"
              }`}
            >{t.label}</button>
          ))}
        </div>
      </div>

      {/* -- tab content -- */}
      {tab === "crm" && <CsvGenerator apiKey={apiKey} />}
      {tab === "bot" && <FraudBot apiKey={apiKey} authToken={token} />}

      {tab === "dashboard" && (
        <div className="px-6 py-5 max-w-[1400px] mx-auto">

          {/* stat cards */}
          <div className="flex gap-3 mb-5 flex-wrap">
            <StatCard
              label="Transactions Processed" value={totals.sent.toLocaleString()}
              pulse colorClass={{ dot: "bg-risk-low", text: "text-risk-low" }}
            />
            <StatCard
              label="Fraud Alerts" value={totals.fraud}
              colorClass={{ text: totals.fraud > 0 ? "text-risk-high" : "text-ink" }}
            />
            <StatCard
              label="Alert Rate" value={`${alertRate}%`}
              colorClass={{ text: parseFloat(alertRate) > 3 ? "text-risk-high" : "text-risk-low" }}
              sub="flagged by either model"
            />
            <StatCard
              label="Data Drift"
              value={drift == null ? "—" : driftIsOn ? "Detected" : "Normal"}
              colorClass={{ text: driftIsOn ? "text-risk-medium" : "text-risk-low" }}
              sub={driftIsOn
                ? `${drift.drifted_features?.length} feature(s) drifting`
                : drift ? `window: ${drift.window_size} txns` : "waiting for data"}
            />
          </div>

          {/* drift banner */}
          {driftIsOn && (
            <div className="bg-[#1c1500] border border-risk-medium rounded-xl px-4.5 py-3.5 mb-4 flex items-start gap-3">
              <span className="text-xl">⚠️</span>
              <div>
                <div className="font-semibold text-risk-medium mb-1.5">
                  Data drift detected (max Z-score {drift.max_z_score})
                </div>
                <div className="flex gap-1.5 flex-wrap mb-2">
                  {drift.drifted_features?.map(f => (
                    <Badge key={f.feature} className="text-risk-medium bg-[#451a03]">
                      {f.feature}  z={f.z_score}
                    </Badge>
                  ))}
                </div>
                <div className="text-xs text-ink-muted">
                  Incoming transaction distribution is shifting from training data. Model accuracy may degrade — consider retraining.
                  {" "}<button onClick={() => setTab("bot")} className="bg-transparent border-none text-risk-medium cursor-pointer text-xs p-0 underline">
                    Ask the Fraud Bot
                  </button> for analysis.
                </div>
              </div>
            </div>
          )}

          {/* chart + model comparison */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 mb-4">
            <Card>
              <CardTitle sub={`Last ${MAX_CHART} transactions · higher = more suspicious · 0 = decision boundary`}>
                Live Risk Scores
              </CardTitle>
              {chart.length === 0 ? (
                <div className="h-[260px] flex items-center justify-center text-ink-muted text-[13px]">
                  Waiting for stream — run stream_simulator.py in a terminal …
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3e" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8892a4" }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: "#8892a4" }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 12 }} formatter={v => <span className="text-ink">{v}</span>} />
                    <ReferenceLine y={0} stroke="#2a2d3e" strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="IF" name="Isolation Forest" stroke="#818cf8" dot={false} strokeWidth={1.8} activeDot={{ r: 4 }} />
                    <Line type="monotone" dataKey="AE" name="Autoencoder"      stroke="#f59e0b" dot={false} strokeWidth={1.8} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>

            <Card>
              <CardTitle sub="Evaluated on held-out test set">Model Comparison</CardTitle>
              {metrics ? (
                <>
                  <div className="grid grid-cols-[1fr_72px_72px] text-[11px] font-semibold text-ink-muted pb-2.5 border-b border-border uppercase tracking-wide">
                    <span>Metric</span>
                    <span className="text-right text-accent-indigo">IF</span>
                    <span className="text-right text-risk-medium">AE</span>
                  </div>
                  {[["PR-AUC","pr_auc",true],["ROC-AUC","roc_auc",false],["Precision","precision",false],["Recall","recall",false],["F1","f1",false]].map(([label, key, bold]) => {
                    const iv = metrics.isolation_forest?.[key];
                    const av = metrics.autoencoder?.[key];
                    const winner = (iv ?? 0) >= (av ?? 0) ? "if" : "ae";
                    return (
                      <div key={key} className="grid grid-cols-[1fr_72px_72px] py-2.5 border-b border-border items-center">
                        <span className={`text-xs text-ink-muted ${bold ? "font-semibold" : "font-normal"}`}>{label}</span>
                        <span className={`text-right font-semibold text-[13px] ${winner === "if" ? "text-accent-indigo" : "text-ink"}`}>{iv?.toFixed(3) ?? "—"}</span>
                        <span className={`text-right font-semibold text-[13px] ${winner === "ae" ? "text-risk-medium" : "text-ink"}`}>{av?.toFixed(3) ?? "—"}</span>
                      </div>
                    );
                  })}
                  <div className="mt-3.5 text-[11px] text-ink-muted leading-relaxed">
                    <strong className="text-ink">PR-AUC</strong> is the key metric — ROC-AUC looks inflated with only 0.17% fraud.
                  </div>
                </>
              ) : (
                <div className="text-ink-muted text-[13px]">Loading metrics…</div>
              )}
            </Card>
          </div>

          {/* fraud alerts table */}
          <Card>
            <CardTitle sub={`Last ${MAX_ALERTS} transactions flagged as fraud by either model`}>
              Recent Fraud Alerts
            </CardTitle>
            {alerts.length === 0 ? (
              <div className="text-center py-8 text-ink-muted text-[13px]">
                {totals.sent === 0
                  ? "No transactions yet — run stream_simulator.py in a terminal."
                  : "No fraud alerts yet. Keep streaming…"}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-border">
                      {["#","Transaction ID","Amount","IF Score","AE Score","IF Flag","AE Flag","Risk","Time"].map(h => (
                        <th key={h} className="text-left px-2.5 py-2 font-medium text-ink-muted text-[11px] uppercase tracking-wide whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a, i) => (
                      <tr key={i} className={`border-b border-border ${i === 0 ? "bg-red-500/[0.06]" : ""}`}>
                        <td className="px-2.5 py-2.5 text-ink-muted">{a.seq}</td>
                        <td className="px-2.5 py-2.5 font-mono text-xs">{a.transaction_id}</td>
                        <td className="px-2.5 py-2.5">${parseFloat(a.amount ?? 0).toFixed(2)}</td>
                        <td className="px-2.5 py-2.5 text-accent-indigo font-semibold">{a.if_score?.toFixed(4)}</td>
                        <td className="px-2.5 py-2.5 text-risk-medium font-semibold">{a.ae_score?.toFixed(4)}</td>
                        <td className="px-2.5 py-2.5">{a.if_fraud ? <Badge className="text-red-300 bg-red-950">YES</Badge> : <Badge>no</Badge>}</td>
                        <td className="px-2.5 py-2.5">{a.ae_fraud ? <Badge className="text-red-300 bg-red-950">YES</Badge> : <Badge>no</Badge>}</td>
                        <td className="px-2.5 py-2.5"><Badge className={LEVEL_CLASSES[a.risk_level] ?? LEVEL_CLASSES.LOW}>{a.risk_level}</Badge></td>
                        <td className="px-2.5 py-2.5 text-ink-muted text-[11px] whitespace-nowrap">{a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="text-center py-6 pb-2 text-ink-muted text-[11px]">
            Fraud Detection Pipeline · IF + AE + Drift Detection · Gemini AI · PostgreSQL
          </div>
        </div>
      )}
    </>
  );
}
