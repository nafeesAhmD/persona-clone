import logging
from collections.abc import Generator

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

def engine_options(settings: Settings) -> dict:
    """Pool and timeouts for the engine. PostgreSQL gets a sized pool and a per-statement
    time limit (DB_STATEMENT_TIMEOUT_MS); other databases (tests) keep SQLAlchemy's defaults."""
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        return {"pool_pre_ping": True}
    connect_args: dict = {"connect_timeout": 5}
    if settings.db_statement_timeout_ms > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout_ms}"
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "connect_args": connect_args,
    }


engine = create_engine(get_settings().database_url, **engine_options(get_settings()))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", exc)
        return False
