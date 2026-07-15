"""
app.py  —  Step 3

FastAPI fraud detection service with:
  • POST /score      — score one transaction with both models, persist to PostgreSQL
  • GET  /ws         — WebSocket; every scored transaction is broadcast here
  • GET  /history    — last 200 scored transactions (read from PostgreSQL)
  • GET  /model-comparison — saved training metrics (IF vs AE)
  • GET  /drift-status     — current drift detector state
  • GET  /drift-events     — historical drift events (audit trail, from PostgreSQL)
  • GET  /health

Run:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from drift_detector import DriftDetector
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session
from fastapi import HTTPException

from auth import (
    create_access_token,
    get_current_user,
    get_current_user_ws,
    hash_password,
    verify_password,
)
from database import SessionLocal, get_db, init_db
from models_db import DriftEvent, ScoredTransaction, User

load_dotenv()

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

MODEL_IF_PATH  = os.getenv("MODEL_IF_PATH",  str(PROJECT_ROOT / "models" / "isolation_forest.pkl"))
MODEL_AE_PATH  = os.getenv("MODEL_AE_PATH",  str(PROJECT_ROOT / "models" / "autoencoder.pkl"))
AE_SCALER_PATH = os.getenv("AE_SCALER_PATH", str(PROJECT_ROOT / "models" / "ae_scaler.pkl"))
SCALER_PATH    = os.getenv("SCALER_PATH",     str(PROJECT_ROOT / "models" / "scaler.pkl"))
METRICS_PATH   = os.getenv("METRICS_PATH",    str(PROJECT_ROOT / "models" / "comparison_metrics.json"))
REF_STATS_PATH = os.getenv("REF_STATS_PATH",  str(PROJECT_ROOT / "models" / "reference_stats.json"))

IF_THRESHOLD = float(os.getenv("IF_THRESHOLD", "0.0"))   # IF score > this → fraud
DRIFT_WINDOW = int(os.getenv("DRIFT_WINDOW",   "100"))    # sliding window size
DRIFT_Z      = float(os.getenv("DRIFT_Z",      "3.0"))    # Z-score threshold
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if o.strip()]

# ── globals (loaded at startup) ───────────────────────────────────────────────
if_model  = None
ae_model  = None
ae_scaler = None
scaler    = None
ae_threshold = 0.0
metrics   = {}
drift_detector: DriftDetector | None = None
history_cache = deque(maxlen=200)   # fast in-memory cache mirroring the DB
was_drifting  = False              # tracks drift state transitions for DriftEvent logging

FEATURE_ORDER = [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"]


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global if_model, ae_model, ae_scaler, scaler, ae_threshold, metrics, drift_detector

    for path, label in [
        (MODEL_IF_PATH,  "Isolation Forest"),
        (MODEL_AE_PATH,  "Autoencoder"),
        (AE_SCALER_PATH, "AE scaler"),
        (SCALER_PATH,    "Feature scaler"),
        (METRICS_PATH,   "Metrics JSON"),
        (REF_STATS_PATH, "Reference stats"),
    ]:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{label} not found at: {os.path.abspath(path)}\n"
                f"Run preprocess.py then train_models.py first."
            )

    if_model  = joblib.load(MODEL_IF_PATH)
    ae_model  = joblib.load(MODEL_AE_PATH)
    ae_scaler = joblib.load(AE_SCALER_PATH)
    scaler    = joblib.load(SCALER_PATH)

    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    ae_threshold = metrics["autoencoder"]["threshold"]

    drift_detector = DriftDetector.from_file(
        REF_STATS_PATH,
        window_size=DRIFT_WINDOW,
        z_threshold=DRIFT_Z,
    )

    # Create PostgreSQL tables if they don't exist yet, and warm the
    # in-memory cache from the last 200 rows so a server restart doesn't
    # blank the dashboard.
    init_db()
    with SessionLocal() as db:
        rows = (
            db.query(ScoredTransaction)
            .order_by(desc(ScoredTransaction.id))
            .limit(200)
            .all()
        )
        for row in reversed(rows):
            history_cache.append(row.to_dict())

    print(f"All models and artefacts loaded. DB warm cache: {len(history_cache)} rows.")
    yield


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fraud Detection API v2",
    description="Isolation Forest + Autoencoder with drift detection, PostgreSQL persistence, and WebSocket streaming.",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── schemas ───────────────────────────────────────────────────────────────────

class Transaction(BaseModel):
    Time: float; Amount: float
    V1:  float; V2:  float; V3:  float; V4:  float; V5:  float
    V6:  float; V7:  float; V8:  float; V9:  float; V10: float
    V11: float; V12: float; V13: float; V14: float; V15: float
    V16: float; V17: float; V18: float; V19: float; V20: float
    V21: float; V22: float; V23: float; V24: float; V25: float
    V26: float; V27: float; V28: float
    transaction_id: str | None = Field(default=None)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── helpers ───────────────────────────────────────────────────────────────────

def risk_level(if_score: float, ae_score: float) -> str:
    if if_score > IF_THRESHOLD and ae_score > ae_threshold:
        return "HIGH"
    if if_score > IF_THRESHOLD or ae_score > ae_threshold:
        return "MEDIUM"
    return "LOW"


def score_both(features: np.ndarray, raw: dict) -> dict:
    # Isolation Forest
    if_score = float(-if_model.decision_function(features)[0])
    if_fraud = if_score > IF_THRESHOLD

    # Autoencoder
    X_ae    = ae_scaler.transform(features)
    X_recon = ae_model.predict(X_ae)
    ae_score = float(np.mean((X_ae - X_recon) ** 2))
    ae_fraud = ae_score > ae_threshold

    is_fraud = if_fraud or ae_fraud

    return {
        "if_score":  round(if_score,  6),
        "ae_score":  round(ae_score,  6),
        "if_fraud":  if_fraud,
        "ae_fraud":  ae_fraud,
        "is_fraud":  is_fraud,
        "risk_level": risk_level(if_score, ae_score),
    }


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "models_loaded": if_model is not None and ae_model is not None,
    }


@app.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")

    user = User(username=payload.username, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()

    token = create_access_token(username=user.username)
    return TokenResponse(access_token=token)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token(username=user.username)
    return TokenResponse(access_token=token)


@app.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "created_at": current_user.created_at}


@app.post("/score")
async def score_transaction(
    txn: Transaction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    global was_drifting

    raw = txn.model_dump()

    ta_scaled = scaler.transform(
        pd.DataFrame([[raw["Time"], raw["Amount"]]], columns=["Time", "Amount"])
    )[0]
    raw["Time"], raw["Amount"] = ta_scaled[0], ta_scaled[1]

    features = np.array([[raw[c] for c in FEATURE_ORDER]])
    scored = score_both(features, raw)

    # Drift check
    drift_detector.add(features[0])
    drift = drift_detector.check()

    # Persist to PostgreSQL
    row = ScoredTransaction(
        transaction_id=txn.transaction_id,
        amount=txn.Amount,
        if_score=scored["if_score"],
        ae_score=scored["ae_score"],
        if_fraud=scored["if_fraud"],
        ae_fraud=scored["ae_fraud"],
        is_fraud=scored["is_fraud"],
        risk_level=scored["risk_level"],
        drift_detected=drift.get("drift_detected", False),
        max_z_score=drift.get("max_z_score", 0.0),
    )
    db.add(row)

    # Log a drift audit event only on the false → true transition, so the
    # drift_events table stays a meaningful timeline rather than one row
    # per transaction while drifting.
    if drift.get("drift_detected") and not was_drifting:
        db.add(DriftEvent(
            max_z_score=drift.get("max_z_score", 0.0),
            drifted_features=json.dumps(drift.get("drifted_features", [])),
            window_size=drift.get("window_size", 0),
        ))
    was_drifting = bool(drift.get("drift_detected"))

    db.commit()
    db.refresh(row)

    result = row.to_dict()
    result["drift"] = drift  # full drift payload (drifted feature list etc.)

    history_cache.append(result)
    await manager.broadcast(result)
    return result


@app.get("/history")
def get_history(
    db: Session = Depends(get_db),
    limit: int = 200,
    current_user: User = Depends(get_current_user),
):
    """Reads straight from PostgreSQL so history survives server restarts."""
    limit = max(1, min(limit, 500))
    rows = (
        db.query(ScoredTransaction)
        .order_by(desc(ScoredTransaction.id))
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in reversed(rows)]


@app.get("/drift-events")
def get_drift_events(
    db: Session = Depends(get_db),
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Audit trail of drift onset events, for the 'has this happened before' question."""
    limit = max(1, min(limit, 200))
    rows = (
        db.query(DriftEvent)
        .order_by(desc(DriftEvent.id))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "max_z_score": r.max_z_score,
            "drifted_features": json.loads(r.drifted_features or "[]"),
            "window_size": r.window_size,
            "timestamp": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reversed(rows)
    ]


@app.get("/model-comparison")
def model_comparison(current_user: User = Depends(get_current_user)):
    return metrics


@app.get("/drift-status")
def drift_status(current_user: User = Depends(get_current_user)):
    return drift_detector.check() if drift_detector else {"error": "not loaded"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Browsers can't set an Authorization header on a native WebSocket, so
    # the token is passed as a query param: ws://.../ws?token=<jwt>
    with SessionLocal() as db:
        await get_current_user_ws(ws, db)  # raises WebSocketException(1008) if invalid

    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep alive; client can send pings
    except WebSocketDisconnect:
        manager.disconnect(ws)
