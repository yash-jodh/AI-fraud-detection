"""
auth.py

JWT authentication for the dashboard.

  • Passwords are hashed with bcrypt (passlib) — never stored in plaintext.
  • Login issues a signed JWT access token (default: valid 24 hours).
  • get_current_user is a FastAPI dependency that protects any route by
    requiring a valid `Authorization: Bearer <token>` header.
  • get_current_user_ws does the same for the WebSocket, which can't send
    custom headers from the browser — so the token is passed as a query
    param instead: ws://localhost:8000/ws?token=...

SECRET_KEY MUST be overridden via the SECRET_KEY env var in production —
the default here is only for local development.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models_db import User

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(
        plain_password[:72],
        hashed_password,
    )


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> str:
    """Returns the username from a valid token, or raises."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise JWTError("Missing subject")
        return username
    except JWTError:
        raise


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Protects HTTP routes. Use as: user: User = Depends(get_current_user)"""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        username = _decode_token(token)
    except JWTError:
        raise credentials_error

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_error
    return user


async def get_current_user_ws(websocket: WebSocket, db: Session) -> User:
    """Protects the WebSocket. Token is passed as ?token=... since the
    browser WebSocket API can't set an Authorization header."""
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    try:
        username = _decode_token(token)
    except JWTError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return user
