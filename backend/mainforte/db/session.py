from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mainforte.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(s.sqlalchemy_url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """For Celery tasks and scripts."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
