"""
init_db.py — Step 0 (run once before starting the API)

Creates the PostgreSQL tables used by the app (scored_transactions, drift_events).

Run:
    python init_db.py
"""

from database import engine, init_db


def main():
    print(f"Connecting to: {engine.url}")
    init_db()
    print("Tables created (or already existed): scored_transactions, drift_events")


if __name__ == "__main__":
    main()
