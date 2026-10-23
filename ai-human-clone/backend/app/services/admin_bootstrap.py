"""How administrators come to exist. There is deliberately no API for it.

- `python -m app.cli create-admin` (see app/cli.py), run by whoever operates the server.
- INITIAL_ADMIN_EMAIL: at startup, an *existing* active account with that email is
  made admin, but only while the platform has no admin at all. Once one exists the
  variable does nothing, so it can't be used later to take over the platform.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AdminAuditLog, User

logger = logging.getLogger(__name__)


def admin_exists(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))))


def grant_admin(db: Session, user: User, source: str) -> None:
    """Make `user` an administrator and record it (actor = the user, source = how)."""
    user.is_admin = True
    db.add(
        AdminAuditLog(
            admin_user_id=user.id,
            action="ADMIN_GRANTED",
            target_type="user",
            target_id=str(user.id),
            details={"source": source},
        )
    )
    db.commit()
    logger.warning("User %s was made an administrator (%s)", user.id, source)


def promote_initial_admin() -> bool:
    email = (get_settings().initial_admin_email or "").strip().lower()
    if not email:
        return False
    try:
        with SessionLocal() as db:
            if admin_exists(db):
                return False
            user = db.scalar(select(User).where(func.lower(User.email) == email))
            if user is None or not user.is_active:
                logger.warning("INITIAL_ADMIN_EMAIL is set but no active account uses it yet")
                return False
            grant_admin(db, user, "INITIAL_ADMIN_EMAIL")
            return True
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Could not apply INITIAL_ADMIN_EMAIL: %s", type(exc).__name__)
        return False
