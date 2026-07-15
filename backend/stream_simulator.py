"""
stream_simulator.py  —  Step 4

Replays creditcard.csv rows to the FastAPI /score endpoint one by one,
simulating a real-time transaction stream. Results from BOTH models
(Isolation Forest and Autoencoder) are printed, and drift warnings are
shown whenever the drift detector fires.

The FastAPI server (app.py) must be running first.

Run:
    python stream_simulator.py
    python stream_simulator.py --limit 500 --delay 0.1 --shuffle
    python stream_simulator.py --fraud-only --delay 0.5
"""

import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests

SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_ROOT= SCRIPT_DIR.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "creditcard.csv"

FEATURE_COLS = [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"]

R  = "\033[91m"; G = "\033[92m"; Y = "\033[93m"
C  = "\033[96m"; B = "\033[1m";  X = "\033[0m"


def banner():
    print(f"\n{B}{C}{'─'*70}{X}")
    print(f"{B}{C}  Fraud Detection Stream  —  Isolation Forest + Autoencoder{X}")
    print(f"{B}{C}{'─'*70}{X}\n")


def check_server(api_url: str) -> bool:
    try:
        r = requests.get(f"{api_url}/health", timeout=3)
        if r.status_code == 200 and r.json().get("models_loaded"):
            print(f"{G}✓ API up — both models loaded.{X}\n")
            return True
    except requests.ConnectionError:
        pass
    print(f"{R}✗ Cannot reach {api_url}/health{X}")
    print(f"  Start the server first:  {Y}uvicorn app:app --host 0.0.0.0 --port 8000 --reload{X}\n")
    return False


def get_auth_token(api_url: str, username: str, password: str) -> str | None:
    """Logs in (registering the user first if needed) and returns a JWT.
    /score is now a protected route, so the simulator needs a token same
    as the dashboard does."""
    login_payload = {"username": username, "password": password}

    r = requests.post(f"{api_url}/auth/login", json=login_payload, timeout=5)
    if r.status_code == 401:
        # User doesn't exist yet — register it, then it's already logged in.
        r = requests.post(f"{api_url}/auth/register", json=login_payload, timeout=5)

    if not r.ok:
        print(f"  {R}Auth error: {r.status_code} {r.text}{X}")
        return None

    return r.json()["access_token"]


def score(api_url: str, payload: dict, token: str) -> dict | None:
    try:
        r = requests.post(
            f"{api_url}/score",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"  {R}API error: {e}{X}")
        return None


def print_result(res: dict, true_label: int, seq: int, alert_count: int):
    tid      = res.get("transaction_id", "?")
    level    = res["risk_level"]
    if_sc    = res["if_score"]
    ae_sc    = res["ae_score"]
    is_fraud = res["is_fraud"]
    drift    = res.get("drift", {})

    if is_fraud:
        tag = f"{R}{B}[FRAUD  HIGH]{X}"
    elif level == "MEDIUM":
        tag = f"{Y}[SUSPICIOUS ]{X}"
    else:
        tag = f"{G}[    OK     ]{X}"

    true_str = f"{'fraud' if true_label == 1 else 'legit':5s}"
    if_col   = R if res["if_fraud"] else G
    ae_col   = R if res["ae_fraud"] else G

    print(
        f"{tag}  {tid:<12s}  "
        f"IF={if_col}{if_sc:+.4f}{X}  AE={ae_col}{ae_sc:.4f}{X}  "
        f"true={true_str}  #{seq} | alerts={alert_count}"
    )

    if drift.get("drift_detected"):
        feats = ", ".join(f["feature"] for f in drift["drifted_features"][:5])
        print(f"  {Y}⚠ Drift detected — {feats}{X}")


def stream(df, api_url, delay, limit, fraud_only, token):
    if fraud_only:
        df = df[df["Class"] == 1].reset_index(drop=True)
        print(f"{Y}Fraud-only mode: {len(df)} fraud transactions.{X}\n")

    total   = min(limit, len(df)) if limit else len(df)
    sent    = 0
    alerts  = 0

    print(f"Streaming {total} transactions  (delay={delay}s)\n")

    for i, row in df.iterrows():
        if limit is not None and sent >= limit:
            break

        payload = {col: float(row[col]) for col in FEATURE_COLS}
        payload["transaction_id"] = f"txn-{i:06d}"
        true_label = int(row.get("Class", -1))

        res = score(api_url, payload, token)
        if res is None:
            continue

        sent  += 1
        if res["is_fraud"]:
            alerts += 1

        print_result(res, true_label, sent, alerts)
        time.sleep(delay)

    print(f"\n{'─'*70}")
    print(f"  Done.  Sent: {sent}  |  Fraud alerts: {alerts}  ({alerts/max(sent,1)*100:.1f}%)")
    print(f"{'─'*70}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",      default=str(DEFAULT_CSV))
    parser.add_argument("--api-url",    default="http://localhost:8000")
    parser.add_argument("--delay",      type=float, default=0.3)
    parser.add_argument("--limit",      type=int,   default=200,
                        help="Max transactions to send (0 = all)")
    parser.add_argument("--shuffle",    action="store_true")
    parser.add_argument("--fraud-only", action="store_true")
    parser.add_argument("--username",   default="simulator",
                        help="Login username used to obtain a JWT (default: simulator)")
    parser.add_argument("--password",   default="simulator-pass",
                        help="Login password (default: simulator-pass)")
    args = parser.parse_args()

    limit = args.limit if args.limit > 0 else None

    if not os.path.exists(args.input):
        raise FileNotFoundError(
            f"\nCould not find: {os.path.abspath(args.input)}\n"
            f"Pass --input with the correct path to creditcard.csv."
        )

    banner()
    if not check_server(args.api_url):
        return

    token = get_auth_token(args.api_url, args.username, args.password)
    if not token:
        print(f"{R}Could not authenticate — aborting.{X}")
        return
    print(f"{G}✓ Authenticated as '{args.username}'.{X}\n")

    df = pd.read_csv(args.input)
    if args.shuffle:
        df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    stream(df, args.api_url, args.delay, limit, args.fraud_only, token)


if __name__ == "__main__":
    main()
