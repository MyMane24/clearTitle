"""Shared extraction schemas keyed by document type."""

from backend.services.schemas.generic import GENERIC_SCHEMA_TEMPLATE, _generic_schema
from backend.services.schemas.static import SCHEMA_MAP

__all__ = [
    "GENERIC_SCHEMA_TEMPLATE",
    "SCHEMA_MAP",
    "_generic_schema",
]
