# Fraud Detection Pipeline v2

Real-time transaction fraud scoring with:
- **Isolation Forest** — fast tree-based anomaly detector
- **Autoencoder** — neural net that learns normal patterns; flags high reconstruction error
- **Drift Detection** — Z-score sliding window; alerts when incoming data shifts away from training distribution
- **PostgreSQL** — persists every scored transaction and every drift-onset event, so history survives a server restart
- **React + Tailwind CSS Dashboard** — live risk score chart, model comparison, fraud alerts table
- **Gemini 3.5 Flash** — CRM call-record generator and a live fraud-monitoring chatbot
- **WebSockets** — real-time push of every scored transaction to the dashboard

```
creditcard.csv
      │
preprocess.py        →  data/processed/  +  models/scaler.pkl
      │
train_models.py      →  models/isolation_forest.pkl
                         models/autoencoder.pkl
                         models/comparison_metrics.json
                         models/reference_stats.json
      │
app.py (uvicorn)     →  http://localhost:8000  ──►  PostgreSQL
      │            ↗  POST /score  (both models + drift check, persisted to DB)
stream_simulator.py  →  WebSocket /ws  →  React + Tailwind Dashboard
                         GET  /history          (reads from PostgreSQL)
                         GET  /model-comparison
                         GET  /drift-status
                         GET  /drift-events      (drift audit trail, from PostgreSQL)
```

---

## Stack

| Layer      | Technology                                   |
|------------|-----------------------------------------------|
| Frontend   | React + Vite + Tailwind CSS                   |
| Backend    | FastAPI                                       |
| Database   | PostgreSQL (via SQLAlchemy)                   |
| ML         | scikit-learn (Isolation Forest, MLP autoencoder) |
| AI         | Gemini API (`gemini-3.5-flash`)               |
| Real-time  | WebSockets                                    |
| Auth       | JWT (python-jose) + bcrypt password hashing   |

---

## Quick start

### 0. Install PostgreSQL and create the database

Install PostgreSQL locally (`postgresql.org/download`, or your OS package manager),
then create a user and database matching `backend/.env.example`:

```sql
CREATE USER fraud_user WITH PASSWORD 'fraud_pass';
CREATE DATABASE fraud_detection OWNER fraud_user;
```

Copy the env template and adjust if your credentials differ:

```bash
cd backend
cp .env.example .env
```

### 1. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Place the dataset

Download from Kaggle ("Credit Card Fraud Detection") and place at:
```
data/creditcard.csv
```

### 3. Preprocess

```bash
cd backend
python preprocess.py
```
Expected: `Train shape: (227845, 30)`

### 4. Train both models

```bash
python train_models.py --contamination 0.0017
```

This takes ~1–3 minutes. It trains Isolation Forest and an Autoencoder,
then saves comparison metrics and reference stats for drift detection.

### 5. Create the PostgreSQL tables

```bash
python init_db.py
```

### 6. Start the API  [Terminal 1 — keep open]

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Check: `http://localhost:8000/health`
Docs:  `http://localhost:8000/docs`

### 7. Start the React dashboard  [Terminal 2 — keep open]

```bash
cd frontend
npm install
npm run dev
```

Open: `http://localhost:5173`

### 8. Stream transactions  [Terminal 3]

```bash
cd backend
python stream_simulator.py --shuffle --limit 300
```

Watch the dashboard update live. Refresh the page at any point — the
dashboard reloads its history straight from PostgreSQL via `GET /history`.

---

## Useful stream flags

| Flag | Effect |
|------|--------|
| `--limit N` | Send N transactions (0 = whole file) |
| `--delay S` | Pause between sends in seconds (default 0.3) |
| `--shuffle` | Randomise order so fraud is mixed in |
| `--fraud-only` | Only send the 492 real fraud rows — great for demos |

**Demo command (fraud only, slow for effect):**
```bash
python stream_simulator.py --fraud-only --delay 0.8
```

**Full dataset, fast:**
```bash
python stream_simulator.py --limit 0 --delay 0.05 --shuffle
```

---

## API endpoints

| Method | Path | Auth required | Description |
|--------|------|:---:|--------------|
| GET | `/health` | – | Liveness check |
| POST | `/auth/register` | – | Create an account, returns a JWT |
| POST | `/auth/login` | – | Log in, returns a JWT |
| GET | `/auth/me` | ✅ | Current logged-in user |
| POST | `/score` | ✅ | Score one transaction with both models, persist to PostgreSQL |
| GET | `/ws` | ✅ (`?token=`) | WebSocket — subscribe to live scored transactions |
| GET | `/history` | ✅ | Last N scored transactions, read from PostgreSQL (default 200) |
| GET | `/drift-events` | ✅ | Audit trail of drift-onset events, from PostgreSQL |
| GET | `/model-comparison` | ✅ | IF vs AE training metrics |
| GET | `/drift-status` | ✅ | Current drift detector state (in-memory sliding window) |

All protected routes expect `Authorization: Bearer <token>`. The WebSocket
can't send custom headers from a browser, so it takes the token as a query
param instead: `ws://localhost:8000/ws?token=<jwt>`.

**Trying it via the API docs (`/docs`):** click **Authorize** in the top
right, paste a token obtained from `/auth/login`, and all protected routes
become callable directly from the Swagger UI.

**Trying it via the dashboard:** the React app now shows a login screen on
first load. Register a user there — no separate setup needed.

**Running `stream_simulator.py`:** it now logs in automatically (registering
a `simulator` user on first run) before it starts posting to `/score`. You
can point it at a different account with `--username` / `--password`.

---

## Tuning

**Risk threshold (Isolation Forest)** and **drift sensitivity** are set via
environment variables — put them in `backend/.env`:

```env
IF_THRESHOLD=0.05     # raise to reduce false positives; lower to catch more fraud
DRIFT_Z=4.0           # less sensitive (default 3.0)
DRIFT_WINDOW=200      # larger window (default 100)
```

---

## Tests

A small pytest suite covers the drift detector's core logic (warm-up state,
no-drift baseline, drift detection on a mean shift, and the drift-event
counter):

```bash
pip install -r backend/requirements.txt
pytest tests/ -v
```

Continuous integration (`.github/workflows/ci.yml`) runs this suite plus a
frontend production build on every push and pull request to `main`.

---

## Project layout

```
fraud-detection-v2/
├── data/
│   ├── creditcard.csv          ← you add this
│   └── processed/              ← created by preprocess.py
├── models/                     ← created by train_models.py
│   ├── isolation_forest.pkl
│   ├── autoencoder.pkl
│   ├── ae_scaler.pkl
│   ├── scaler.pkl
│   ├── comparison_metrics.json
│   └── reference_stats.json
├── backend/
│   ├── preprocess.py
│   ├── train_models.py
│   ├── drift_detector.py
│   ├── database.py             ← SQLAlchemy engine/session
│   ├── models_db.py            ← PostgreSQL ORM models (incl. User)
│   ├── auth.py                 ← JWT + password hashing
│   ├── init_db.py              ← creates tables
│   ├── app.py                  ← FastAPI service
│   ├── stream_simulator.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── index.css           ← Tailwind directives
│       ├── App.jsx
│       ├── Login.jsx
│       ├── CsvGenerator.jsx
│       └── FraudBot.jsx
├── tests/
│   ├── conftest.py
│   └── test_drift_detector.py
├── .github/workflows/ci.yml
├── .gitignore
└── README.md
```

---

## Gemini AI features

Two extra tabs in the dashboard require a **Gemini API key**.

### How to get one
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in → click **Get API key** → Create API key
3. Copy the key (starts with `AIza…`)

### Where to paste it
Paste it in the **Gemini API key** field in the top-right of the dashboard header.
It is held in browser memory only — it is never sent anywhere except directly to Google's Gemini API.

---

### Tab 2 — CRM Fraud Call Generator

Gemini generates a CSV of realistic bank fraud investigation call records — useful for demos, pipeline testing, and presentations.

Each row includes:
`call_id, customer_name, phone, email, account_id, transaction_amount, merchant, fraud_type, risk_score, call_notes, agent_id, call_date, resolution, is_confirmed_fraud`

Options:
- **Scenario** — card-not-present, account takeover, identity theft, phishing, synthetic identity, or mixed
- **Records** — 5 to 100 rows
- **Custom instructions** — freetext (e.g. "focus on elderly victims")

Click **Generate CSV** → preview table appears → click **Download** to save.

---

### Tab 3 — Fraud Monitor Bot

A Gemini-powered chatbot that reads your **live PostgreSQL-backed dashboard data** on every message — transaction counts, fraud alerts, model metrics, drift status, and recent high-risk transactions — and answers questions about them.

Example questions it handles well:
- *"What is the current fraud rate?"*
- *"Which model is flagging more transactions?"*
- *"Is there data drift? What does it mean?"*
- *"Summarise what's happening right now"*
- *"Which transactions look most suspicious?"*

The bot fetches fresh data from the FastAPI `/history`, `/drift-status`, and `/model-comparison` endpoints before every reply, so its answers are always current.

---

## Why this is a strong portfolio project

- **Two contrasting ML approaches on the same problem** (tree-based vs. neural), evaluated side by side with PR-AUC — shows you understand why accuracy alone is misleading on a 0.17%-fraud dataset.
- **Production concerns handled, not just a notebook**: a real database, a typed REST API with OpenAPI docs, WebSockets for real-time delivery, environment-based config, and CI.
- **MLOps awareness**: a drift detector that treats model risk as ongoing, not a one-time training run, with a persisted audit trail of when drift occurred.
- **AI-native feature work**: Gemini integration that reads *live* application state before answering, rather than a static chatbot bolted onto the UI.
