"""The due diligence report contract.

A report is a list of generic sections, each made of typed blocks. The
dashboard renders any section, so adding or renaming a section needs no UI
change: edit ``DEFAULT_SECTIONS`` (and the report prompt).

Every block names the Case File items it rests on in ``refs`` (link, issue,
lead, requisition or document ids). The report gate checks those ids exist.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Opinion = Literal["CLEAR", "CLEAR_SUBJECT_TO", "NOT_CLEAR"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParagraphBlock(_Model):
    type: Literal["paragraph"] = "paragraph"
    text: Text
    refs: list[str] = Field(default_factory=list)


class ListItem(_Model):
    text: Text
    refs: list[str] = Field(default_factory=list)


class ListBlock(_Model):
    type: Literal["list"] = "list"
    items: list[ListItem] = Field(min_length=1)


class TableBlock(_Model):
    type: Literal["table"] = "table"
    columns: list[Text] = Field(min_length=1)
    rows: list[list[str]] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)


class Finding(_Model):
    title: Text
    text: Text
    severity: Literal["high", "medium", "low"] | None = None
    status: str | None = Field(default=None, description="e.g. verified, defective, open.")
    refs: list[str] = Field(default_factory=list)


class FindingsBlock(_Model):
    type: Literal["findings"] = "findings"
    items: list[Finding] = Field(min_length=1)


Block = Annotated[
    ParagraphBlock | ListBlock | TableBlock | FindingsBlock, Field(discriminator="type")
]


class Section(_Model):
    id: Text
    title: Text
    blocks: list[Block] = Field(min_length=1)

    def refs(self) -> set[str]:
        found: set[str] = set()
        for block in self.blocks:
            if isinstance(block, ParagraphBlock | TableBlock):
                found.update(block.refs)
            else:
                for item in block.items:
                    found.update(item.refs)
        return found


class OpinionReason(_Model):
    text: Text
    refs: list[str] = Field(default_factory=list)


class WrittenReport(_Model):
    """What the report writer produces from the Case File."""

    property_summary: Text = Field(description="One paragraph identifying the property.")
    opinion: Opinion
    opinion_reasons: list[OpinionReason] = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)


class DueDiligenceReport(_Model):
    """The saved report: the writer's text plus sections the application builds."""

    version: int = Field(ge=1)
    property_summary: Text
    opinion: Opinion
    opinion_reasons: list[OpinionReason]
    sections: list[Section]
    changes_since_previous: list[str] = Field(default_factory=list)
    basis: dict = Field(
        default_factory=dict,
        description="Snapshot of verdicts, issues and requisitions, used to list changes.",
    )


# (id, title, what the writer puts there). Sections marked "built" are written
# by the application from the Case File, not by the model.
DEFAULT_SECTIONS: list[tuple[str, str, str]] = [
    ("property_schedule", "Property schedule", "Identifiers, extent, boundaries, location."),
    ("documents_examined", "Documents examined", "built"),
    ("flow_of_title", "Flow of title", "The chain as a narrative, earliest first; mark links "
     "added during verification and every recorded break."),
    ("transaction_scrutiny", "Scrutiny of each transaction", "One finding per chain link with "
     "its verdict: vendor's title, parties and capacity, schedule and extent, execution, "
     "registration, stamp duty, consideration, mutation."),
    ("encumbrances", "Encumbrances", "Mortgages and their release, charges, attachments, "
     "agreements, leases."),
    ("revenue_records", "Revenue records", "Whether RTC and mutation records follow each "
     "transfer."),
    ("land_use", "Land use and approvals", "Conversion, khata, plans, tax, grant or PTCL "
     "restrictions."),
    ("red_flags", "Red flags", "Every issue, by severity."),
    ("requisitions", "Requisitions", "built"),
    ("limitations", "Limitations", "Documents not examined, what the records cannot show, "
     "and that the opinion rests only on the documents provided."),
]  # fmt: skip

WRITTEN_SECTION_IDS = [sid for sid, _, how in DEFAULT_SECTIONS if how != "built"]
