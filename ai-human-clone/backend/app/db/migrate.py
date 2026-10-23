"""Apply database migrations. Run before the API starts: `python -m app.db.migrate`.

Safe to run on every start and from several containers at once: a PostgreSQL advisory
lock lets one process upgrade while the others wait, and an up-to-date database is a
no-op. RUN_MIGRATIONS_ON_START=false skips it, for releases that migrate in a separate step.
"""

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import engine

logger = logging.getLogger("app.db.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Databases created by create_all before Alembic was added match this revision.
PRE_ALEMBIC_REVISION = "0001_initial"
# Any fixed 64-bit number shared by every process of this app ("AHC" + "migr").
MIGRATION_LOCK_KEY = 0x4148434D494752


@contextmanager
def migration_lock(connection: Connection) -> Iterator[None]:
    """Hold a session-level PostgreSQL advisory lock (no-op on other databases)."""
    if connection.dialect.name != "postgresql":
        yield
        return
    logger.info("Waiting for the migration lock")
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
    try:
        yield
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})


def _alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


def _wait_for_database(attempts: int = 10, delay: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect():
                return
        except OperationalError:
            if attempt == attempts:
                raise
            logger.warning("Database not ready (attempt %d/%d), retrying", attempt, attempts)
            time.sleep(delay)


def run_migrations() -> None:
    _wait_for_database()
    config = _alembic_config()
    # The lock lives on its own connection; Alembic migrates on separate ones.
    with engine.connect() as lock_connection, migration_lock(lock_connection):
        tables = set(inspect(engine).get_table_names())
        if "alembic_version" not in tables and "users" in tables:
            # Tables exist but were never tracked: record them as the initial revision
            # so the upgrade only applies newer changes and keeps existing data.
            logger.info("Existing schema without migration history; stamping %s", PRE_ALEMBIC_REVISION)
            command.stamp(config, PRE_ALEMBIC_REVISION)
        command.upgrade(config, "head")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if not get_settings().run_migrations_on_start:
        logger.info("RUN_MIGRATIONS_ON_START=false: skipping migrations")
        sys.exit(0)
    try:
        run_migrations()
    except Exception:
        logger.exception("Database migration failed")
        sys.exit(1)
