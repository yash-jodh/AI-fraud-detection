import { useState } from "react";

const API = "http://localhost:8000";

export default function Login({ onLogin }) {
  const [mode,     setMode]     = useState("login"); // "login" | "register"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ?? "Authentication failed");
      }
      onLogin(data.access_token, username.trim());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-surface-card border border-border rounded-xl p-6">
        <div className="text-center mb-6">
          <div className="text-2xl mb-1">🛡</div>
          <div className="font-bold text-lg">Fraud Detection System</div>
          <div className="text-xs text-ink-muted mt-1">
            {mode === "login" ? "Sign in to view the dashboard" : "Create an account"}
          </div>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-3">
          <div>
            <label className="text-xs text-ink-muted block mb-1.5">Username</label>
            <input
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoFocus
              className="w-full bg-surface-base border border-border text-ink rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-ink-muted block mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-surface-base border border-border text-ink rounded-lg px-3 py-2 text-sm"
            />
          </div>

          {error && <div className="text-risk-high text-xs">{error}</div>}

          <button
            type="submit"
            disabled={loading}
            className="bg-accent-indigo text-white border-none rounded-lg py-2 text-sm font-medium cursor-pointer disabled:opacity-60 mt-1"
          >
            {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <div className="text-center mt-4 text-xs text-ink-muted">
          {mode === "login" ? (
            <>No account? <button onClick={() => setMode("register")} className="text-accent-indigo underline bg-transparent border-none cursor-pointer">Register</button></>
          ) : (
            <>Already have an account? <button onClick={() => setMode("login")} className="text-accent-indigo underline bg-transparent border-none cursor-pointer">Sign in</button></>
          )}
        </div>
      </div>
    </div>
  );
}
