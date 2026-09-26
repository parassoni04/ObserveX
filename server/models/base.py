"""
ObserveX Server — SQLAlchemy Declarative Base.

All ORM models inherit from this Base class.
Provides the shared metadata and mapper registry for the entire schema.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base for all ObserveX ORM models."""
    pass
