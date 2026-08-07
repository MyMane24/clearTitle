"""Shared prompt schemas, lazily loadable per document type.

`get_schema(doc_type)` deep-copies the schema on demand so callers can mutate
the returned dict without corrupting the shared template.
"""
from copy import deepcopy

from backend.services.schemas.generic import GENERIC_SCHEMA_TEMPLATE, _generic_schema
from backend.services.schemas.static import SCHEMA_MAP

__all__ = [
    "GENERIC_SCHEMA_TEMPLATE",
    "SCHEMA_MAP",
    "_generic_schema",
    "get_schema",
]


def get_schema(doc_type: str) -> dict:
    """Return a deep copy of the extraction schema for a document type."""
    return deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
