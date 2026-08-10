"""Generic fallback schema for unknown document types."""

from copy import deepcopy

GENERIC_SCHEMA_TEMPLATE = {
    "document_type": None,
    "file_metadata": {
        "document_title": None, "issuing_authority": None,
        "document_date": None, "document_number": None,
    },
    "key_identifiers": {
        "property_identifier": None, "owner_or_party_names": [],
        "location": None,
    },
    "key_values": {},
}
def _generic_schema(doc_type: str) -> dict:
    schema = deepcopy(GENERIC_SCHEMA_TEMPLATE)
    schema["document_type"] = doc_type
    return schema
