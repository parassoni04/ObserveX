from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from server.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency – yields an AsyncSession and closes it after the request."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables defined in models.py."""
    from server.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose the engine connection pool."""
    await engine.dispose()
