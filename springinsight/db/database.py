"""Database engine, session factory, and init for SpringInsight."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

_engine = None
_SessionLocal = None

DB_FILENAME = "springinsight.db"

# Global data directory — shared by CLI and Web UI
GLOBAL_DATA_DIR = Path.home() / ".springinsight"


def _get_db_path(work_dir: Path | None = None) -> Path:
    """Return the path to the SQLite database.

    Always uses the global ~/.springinsight directory so that CLI runs
    and the Web UI share the same database.  The ``work_dir`` parameter
    is retained for backward-compatibility but is no longer used.
    """
    data_dir = GLOBAL_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME


def init_db(work_dir: Path | None = None) -> None:
    """Initialize the database engine and create all tables.

    Must be called once at startup before any DB operations.
    ``work_dir`` is accepted for backward-compatibility but ignored;
    the DB always lives at ``~/.springinsight/springinsight.db``.
    """
    global _engine, _SessionLocal

    db_path = _get_db_path()
    db_url = f"sqlite:///{db_path.as_posix()}"

    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable WAL mode and foreign keys for SQLite
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@contextmanager
def get_db():
    """Yield a DB session with auto-commit/rollback."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_path_for_dir(work_dir: Path | None = None) -> Path:
    return _get_db_path()
