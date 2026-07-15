"""
models_db.py

SQLAlchemy ORM models — these are the PostgreSQL tables backing the app.
Kept separate from the ML models in models/*.pkl (those are pickled
scikit-learn objects; these are database rows).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    """A dashboard login. Passwords are stored as bcrypt hashes only —
    never plaintext (see auth.py: hash_password / verify_password)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ScoredTransaction(Base):
    """One row per transaction scored through POST /score. This is the
    persistent, queryable history — the in-memory deque in app.py is just
    a fast cache for the most recent 200 so the dashboard loads instantly."""

    __tablename__ = "scored_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float)

    if_score: Mapped[float] = mapped_column(Float)
    ae_score: Mapped[float] = mapped_column(Float)
    if_fraud: Mapped[bool] = mapped_column(Boolean)
    ae_fraud: Mapped[bool] = mapped_column(Boolean)
    is_fraud: Mapped[bool] = mapped_column(Boolean, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), index=True)

    drift_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    max_z_score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
            "amount": self.amount,
            "if_score": self.if_score,
            "ae_score": self.ae_score,
            "if_fraud": self.if_fraud,
            "ae_fraud": self.ae_fraud,
            "is_fraud": self.is_fraud,
            "risk_level": self.risk_level,
            "drift": {
                "drift_detected": self.drift_detected,
                "max_z_score": self.max_z_score,
            },
        }


class DriftEvent(Base):
    """One row every time the drift detector flips into a drifted state —
    an audit trail of model degradation over time, independent of the
    live sliding-window state kept in memory."""

    __tablename__ = "drift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    max_z_score: Mapped[float] = mapped_column(Float)
    drifted_features: Mapped[str] = mapped_column(Text)  # JSON-encoded list
    window_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
