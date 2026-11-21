"""The due diligence report contract: what the buyer's report page shows, nothing more.

The model writes only the opinion and one or two reasons. The application builds
the findings and the changes from the Case File.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Opinion = Literal["CLEAR", "CLEAR_SUBJECT_TO", "NOT_CLEAR"]
Severity = Literal["high", "medium", "low", "clear"]


class Finding(BaseModel):
    """One finding card: a problem (high, medium, low) or a check that passed (clear)."""

    model_config = ConfigDict(extra="forbid")

    title: Text
    text: Text
    severity: Severity


class WrittenReport(BaseModel):
    """What the report writer produces from the Case File."""

    model_config = ConfigDict(extra="forbid")

    opinion: Opinion
    reasons: list[Text] = Field(min_length=1, description="One or two short reasons.")


class DueDiligenceReport(BaseModel):
    """The saved report."""

    model_config = ConfigDict(extra="ignore")

    version: int = Field(ge=1)
    opinion: Opinion
    reasons: list[str]
    findings: list[Finding] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_older_shape(cls, data):
        """Read reports saved before 2026-11-21, which used generic sections."""
        if not isinstance(data, dict) or "sections" not in data:
            return data
        findings = [
            {
                "title": item["title"],
                "text": item["text"],
                "severity": item.get("severity") or "low",
            }
            for section in data.get("sections") or []
            if section.get("id") == "issues"
            for block in section.get("blocks") or []
            if block.get("type") == "findings"
            for item in block.get("items") or []
        ]
        return {
            "version": data.get("version"),
            "opinion": data.get("opinion"),
            "reasons": [
                reason["text"] if isinstance(reason, dict) else reason
                for reason in data.get("opinion_reasons") or []
            ],
            "findings": findings,
            "changes": data.get("changes_since_previous") or [],
        }
