"""Database engine and session setup (SQLAlchemy 2.x)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        # SQLite connections are used from FastAPI's thread pool.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()
