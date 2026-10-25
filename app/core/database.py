"""
Database engines and sessions (SQL Server via async `mssql+aioodbc`, plan §4.1, DEC-24).

Engines are created lazily on first use, so importing the app (tests, Alembic, tooling)
never loads the ODBC driver or opens a connection.

Rules (plan §7 / reference conventions):
- Routers stay thin; services own SQL and transactions.
- Writer session for anything that writes; reader session for read-only queries.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _make_engine(url: str) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        echo=settings.DB_ECHO,
        # Executemany speed-up for pyodbc; safe for SQL Server.
        fast_executemany=True,
    )


@lru_cache
def get_writer_engine() -> AsyncEngine:
    return _make_engine(get_settings().writer_url)


@lru_cache
def get_reader_engine() -> AsyncEngine:
    settings = get_settings()
    if settings.DB_READER_URL is None:
        # Same login and server (DEC-32): share the writer pool.
        return get_writer_engine()
    return _make_engine(settings.reader_url)


@lru_cache
def _writer_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_writer_engine(), expire_on_commit=False, autoflush=False)


@lru_cache
def _reader_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_reader_engine(), expire_on_commit=False, autoflush=False)


async def get_writer_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: writer session."""
    async with _writer_sessionmaker()() as session:
        yield session


async def get_reader_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: reader session."""
    async with _reader_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def get_db_session(use_reader: bool = False) -> AsyncGenerator[AsyncSession, None]:
    """Programmatic access outside FastAPI dependencies (CLI, workers)."""
    factory = _reader_sessionmaker() if use_reader else _writer_sessionmaker()
    async with factory() as session:
        yield session


async def dispose_engines() -> None:
    """Dispose engines that were actually created (called on shutdown)."""
    for getter in (get_reader_engine, get_writer_engine):
        if getter.cache_info().currsize:
            await getter().dispose()
