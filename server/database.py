"""
ObserveX Server — Database Engine & Session Factory.

Manages the async SQLAlchemy engine and session factory.
Supports PostgreSQL (production) with automatic fallback to
SQLite (development/small deployments).

The hacky ALTER TABLE migration code from the old architecture
has been removed. Use Alembic for schema migrations.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from server.config import settings


def _build_engine(db_url: str):
    """Create an async SQLAlchemy engine with appropriate settings."""
    kwargs = {"echo": False}
    if "sqlite" not in db_url:
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
        })
    return create_async_engine(db_url, **kwargs)


engine = _build_engine(settings.DATABASE_URL)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


def get_session():
    """Return an AsyncSession from the current active factory."""
    return async_session_factory()


async def get_db():
    """FastAPI dependency — yields an AsyncSession."""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """
    Create all tables. Falls back to SQLite if PostgreSQL is unavailable.

    In production, use Alembic migrations instead of create_all().
    This auto-creation is a convenience for development.
    """
    global engine, async_session_factory
    from server.models import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        if "sqlite" not in str(engine.url):
            print(
                "[ObserveX Server] PostgreSQL connection failed. "
                "Falling back to local SQLite database..."
            )
            fallback_url = "sqlite+aiosqlite:///./observex_local.db"
            engine = _build_engine(fallback_url)
            async_session_factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("[ObserveX Server] SQLite database initialized successfully.")
        else:
            raise e


async def close_db():
    """Dispose of the database engine on shutdown."""
    await engine.dispose()
