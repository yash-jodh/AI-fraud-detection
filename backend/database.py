"""
database.py

SQLAlchemy engine, session factory, and connection setup for PostgreSQL.

Connection is configured entirely through environment variables (see .env.example)
so the same code runs locally, in Docker, or against a managed Postgres instance
(Render, Supabase, RDS, etc.) without any code changes — just swap DATABASE_URL.

Falls back to a local SQLite file if DATABASE_URL is not set, so the project
still boots for a quick demo even without Postgres running. For placement
interviews / grading, set DATABASE_URL to Postgres to show the real stack.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:yash@localhost:5432/fraud_detection",
)

# Allow a graceful local fallback if someone runs this without Postgres installed.
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Safe to call repeatedly (no-op if they exist)."""
    import models_db  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)
