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


def _get_db_path(work_dir: Path) -> Path:
    data_dir = work_dir / ".springinsight"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME


def init_db(work_dir: Path) -> None:
    """Initialize the database engine and create all tables.

    Must be called once at startup before any DB operations.
    work_dir is the SpringInsight working directory (contains context.yaml).
    """
    global _engine, _SessionLocal

    db_path = _get_db_path(work_dir)
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


def get_db_path_for_dir(work_dir: Path) -> Path:
    return _get_db_path(work_dir)
