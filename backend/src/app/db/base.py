"""
SQLAlchemy declarative base for all ORM models.

Ref: spec/database.md §1.1
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass
