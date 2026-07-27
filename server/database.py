from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from server.config import settings

def _build_engine(db_url: str):
    kwargs = {"echo": False}
    if "sqlite" not in db_url:
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
            "connect_args": {"timeout": 3}
        })
    return create_async_engine(db_url, **kwargs)

engine = _build_engine(settings.DATABASE_URL)

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
    """Create all tables defined in models.py with fallback to SQLite if PostgreSQL is unavailable."""
    global engine, async_session_factory
    from server.models import Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        if "sqlite" not in str(engine.url):
            print(f"[ObserveX Server] PostgreSQL connection failed. Falling back to local SQLite database...")
            fallback_url = "sqlite+aiosqlite:///./observex_local.db"
            engine = _build_engine(fallback_url)
            async_session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("[ObserveX Server] SQLite database initialized successfully.")
        else:
            raise e


async def close_db():
    """Dispose the engine connection pool."""
    await engine.dispose()
