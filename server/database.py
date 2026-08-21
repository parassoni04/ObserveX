from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from server.config import settings


def _build_engine(db_url: str):
    kwargs = {"echo": False}
    if "sqlite" not in db_url:
        kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True, "connect_args": {"timeout": 3}})
    return create_async_engine(db_url, **kwargs)


engine = _build_engine(settings.DATABASE_URL)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency – yields an AsyncSession."""
    async with async_session_factory() as session:
        yield session


async def _migrate_add_missing_columns(conn):
    """
    Add missing columns to existing tables (for SQLite where ALTER TABLE ADD COLUMN works).
    This handles the case where the DB was created with an older schema.
    """
    from server.models import Base

    def _sync_migrate(connection):
        insp = inspect(connection)
        for table_name, table in Base.metadata.tables.items():
            if not insp.has_table(table_name):
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(dialect=connection.dialect)
                    default = ""
                    if col.default is not None and hasattr(col.default, "arg") and isinstance(col.default.arg, (str, int, float, bool)):
                        val = col.default.arg
                        if isinstance(val, str):
                            default = f" DEFAULT '{val}'"
                        elif isinstance(val, bool):
                            default = f" DEFAULT {1 if val else 0}"
                        else:
                            default = f" DEFAULT {val}"
                    nullable = "" if col.nullable else " NOT NULL" + (default if default else " DEFAULT ''")
                    if not nullable:
                        nullable = default
                    try:
                        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{nullable}"))
                        print(f"[DB Migration] Added column '{col.name}' to table '{table_name}'")
                    except Exception as e:
                        if "duplicate column" not in str(e).lower():
                            print(f"[DB Migration] Warning: could not add column '{col.name}' to '{table_name}': {e}")

    conn.run_callable(_sync_migrate)


async def init_db():
    """Create all tables with fallback to SQLite if PostgreSQL is unavailable."""
    global engine, async_session_factory
    from server.models import Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Migrate: add missing columns to existing tables
            await conn.run_sync(lambda c: _sync_add_missing_columns(c))
    except Exception as e:
        if "sqlite" not in str(engine.url):
            print("[ObserveX Server] PostgreSQL connection failed. Falling back to local SQLite database...")
            fallback_url = "sqlite+aiosqlite:///./observex_local.db"
            engine = _build_engine(fallback_url)
            async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(lambda c: _sync_add_missing_columns(c))
            print("[ObserveX Server] SQLite database initialized successfully.")
        else:
            raise e


def _sync_add_missing_columns(connection):
    """Synchronous helper for adding missing columns within run_sync context."""
    from server.models import Base
    insp = inspect(connection)
    for table_name, table in Base.metadata.tables.items():
        if not insp.has_table(table_name):
            continue
        existing_cols = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing_cols:
                col_type = col.type.compile(dialect=connection.dialect)
                # Build a safe default clause
                default_clause = ""
                if col.default is not None and hasattr(col.default, "arg"):
                    val = col.default.arg
                    if isinstance(val, str):
                        default_clause = f" DEFAULT '{val}'"
                    elif isinstance(val, (int, float)):
                        default_clause = f" DEFAULT {val}"
                    elif isinstance(val, bool):
                        default_clause = f" DEFAULT {1 if val else 0}"

                # SQLite ALTER TABLE ADD COLUMN requires a default for NOT NULL
                null_clause = ""
                if not col.nullable and not default_clause:
                    default_clause = " DEFAULT ''"
                    null_clause = ""
                elif not col.nullable:
                    null_clause = ""

                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                    connection.execute(text(sql))
                    print(f"[DB Migration] Added column '{col.name}' to table '{table_name}'")
                except Exception as e:
                    err_str = str(e).lower()
                    if "duplicate column" not in err_str and "already exists" not in err_str:
                        print(f"[DB Migration] Warning: could not add '{col.name}' to '{table_name}': {e}")


async def close_db():
    await engine.dispose()
