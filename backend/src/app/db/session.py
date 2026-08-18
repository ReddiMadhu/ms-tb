"""
SQLite engine & session factory with WAL mode pragmas.

Ref: spec/database.md §1.1, §4
ADR-002: Embedded SQLite WAL metadata store
ADR-020: SQLite WAL mode + batched audit (PRAGMA journal_mode=WAL)
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings


def _create_engine():
    """Create SQLAlchemy engine with SQLite-specific configuration."""
    db_url = settings.database_url

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        """Apply critical SQLite pragmas per ADR-002 / ADR-020."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    return engine


engine = _create_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables from ORM metadata. Called once at application startup."""
    from app.db.base import Base
    # Import all models so they register with Base.metadata
    import app.models.job  # noqa: F401
    import app.models.objects  # noqa: F401
    import app.models.validation  # noqa: F401
    import app.models.audit  # noqa: F401

    Base.metadata.create_all(bind=engine)
