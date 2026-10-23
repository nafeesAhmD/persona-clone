"""Database sessions for real-time voice. A WebSocket lives for minutes, so it opens a
short session per step instead of holding one (tests point SessionLocal at their DB)."""

from app.db.session import SessionLocal


def open_db():
    return SessionLocal()
