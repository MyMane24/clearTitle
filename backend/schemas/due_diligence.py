"""The due diligence report contract: an advocate-style Report of Investigation of Title.

The model writes the particulars, the documents scrutinised with a paragraph on
each, the history of title, the certificate and the opinion. The application adds
the documents still required, the date and the changes since the previous version,
and renders the same report on the page and as a PDF.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Opinion = Literal["CLEAR", "CLEAR_SUBJECT_TO", "NOT_CLEAR"]
_NO_DATE = re.compile(
    r"\s*[-(]*\s*(?:date\s+)?(?:not\s+(?:stated|given|known|legible)|undated|unknown|n/?a)"
    r"\s*[).]*\s*|\s*-?\s*",
    re.IGNORECASE,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Boundaries(_Model):
    east: str | None = None
    west: str | None = None
    north: str | None = None
    south: str | None = None


class ScrutinizedDocument(_Model):
    """One row of the documents-scrutinised table."""

    doc_id: Text = Field(description="The document's id, as given in the input.")
    date: str = Field(
        default="", description="The document's date, e.g. '06.12.2007'; empty when it has none."
    )
    nature: Text = Field(
        description="What the document is and the property it concerns, e.g. 'Registered Sale "
        "Deed in respect of R.S. No. 699-A/14, situated at Angol Village'."
    )

    @field_validator("date")
    @classmethod
    def _blank_when_not_stated(cls, value: str) -> str:
        """A document without a date shows an empty cell, never "date not stated"."""
        return "" if _NO_DATE.fullmatch(value or "") else (value or "").strip()


class DocumentDetail(_Model):
    """The paragraph on one scrutinised document."""

    doc_id: Text
    text: Text = Field(
        description="One paragraph: its number and date, who executed it in favour of whom, the "
        "property and extent, and what it records."
    )


class WrittenReport(_Model):
    """What the report writer produces from the Case File."""

    opinion: Opinion
    reasons: list[Text] = Field(min_length=1, description="One or two short reasons.")
    title_holders: list[Text] = Field(min_length=1, description="The present owner(s).")
    property_description: Text = Field(
        description="The complete description: plot, CTS, PID, extent, survey number, location."
    )
    boundaries: Boundaries = Field(default_factory=Boundaries)
    documents: list[ScrutinizedDocument] = Field(
        min_length=1, description="Every examined document, oldest first."
    )
    document_details: list[DocumentDetail] = Field(
        min_length=1, description="One paragraph per document, in the same order."
    )
    history: list[Text] = Field(
        min_length=1, description="The history of title, one paragraph per step, oldest first."
    )
    certificate: Text = Field(description="The certificate: the opinion and its conditions.")


class RequiredDocument(_Model):
    document: Text
    reason: Text


class DueDiligenceReport(BaseModel):
    """The saved report. Reports saved before 2026-11-24 carry only the opinion and reasons;
    their other fields are empty and the page says so."""

    model_config = ConfigDict(extra="ignore")

    version: int = Field(ge=1)
    opinion: Opinion
    reasons: list[str] = Field(default_factory=list)
    title_holders: list[str] = Field(default_factory=list)
    property_description: str | None = None
    boundaries: Boundaries = Field(default_factory=Boundaries)
    documents: list[ScrutinizedDocument] = Field(default_factory=list)
    document_details: list[DocumentDetail] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    certificate: str | None = None
    documents_required: list[RequiredDocument] = Field(default_factory=list)
    prepared_on: date | None = None
    changes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_older_shape(cls, data):
        """Read reports saved before 2026-11-21, which used generic sections."""
        if not isinstance(data, dict) or "sections" not in data:
            return data
        return {
            "version": data.get("version"),
            "opinion": data.get("opinion"),
            "reasons": [
                reason["text"] if isinstance(reason, dict) else reason
                for reason in data.get("opinion_reasons") or []
            ],
            "changes": data.get("changes_since_previous") or [],
        }
