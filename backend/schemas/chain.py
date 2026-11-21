"""The title-chain contract: what the chain builder must produce.

The chain is built from the property's history documents (encumbrance
certificate, mutation, RTC), extended backward and
confirmed through title deeds. These models are both the schema the model is
asked to fill and the validation applied before anything is saved.

Transaction ids, upstream links and the chain graph are absent on purpose:
the application adds them after validation.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Acts that never change ownership. A chain link named after one is rejected,
# so a lender or tenant can never appear in the chain as an owner.
_NON_TRANSFER = re.compile(
    r"\b(mortgage|deposit of title|lease|agreement|power of attorney|attachment)\b",
    re.IGNORECASE,
)

def is_non_transfer(label: str) -> bool:
    """True when a transaction label names an act that never changes ownership."""
    return bool(_NON_TRANSFER.search(label))


_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y")


def parse_date(value: str | None) -> date | None:
    """Parse a fully stated date; ``None`` for a missing or partial one."""
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime((value or "").strip(), date_format).date()
        except ValueError:
            continue
    return None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(_Strict):
    """A history document or title deed a fact was taken from."""

    doc_id: Text
    filename: Text = Field(description="The document's uploaded filename, copied exactly.")


class IdentityDetail(_Strict):
    label: Text = Field(
        description="What the value identifies, e.g. Survey number, Village, Extent."
    )
    value: Text
    source_refs: list[SourceRef] = Field(min_length=1)


class PropertyIdentity(_Strict):
    details: list[IdentityDetail] = Field(min_length=1)


class RelatedEvent(_Strict):
    """A recorded event that is not an ownership transfer (mortgage, release, conversion)."""

    type: Text
    summary_points: list[Text] = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)


class DocumentedTransaction(_Strict):
    """One ownership transfer, as the history documents and deeds report it.

    There is no registration-office field on purpose. Documents name the same
    office differently (Belgaum and Belagavi), and the id matcher treats two
    differing office names as two different transactions, so a free-text office
    would give a link a new id on every rebuild.
    """

    @model_validator(mode="before")
    @classmethod
    def _remove_legacy_fields(cls, data: object) -> object:
        """Discard fields saved by older versions or misplaced by the model.

        ``property_type`` was removed on 2026-11-21: the verification verdict records
        what each transfer conveyed. ``missing_documents`` is dropped only when empty.
        """
        if not isinstance(data, dict):
            return data
        drop = {"property_type"}
        if data.get("missing_documents") == []:
            drop.add("missing_documents")
        return {key: value for key, value in data.items() if key not in drop}

    transaction_number: str | None = Field(
        description="Registration or instrument number as written; null when none is stated."
    )
    transaction_type: Text = Field(
        description="Plain label: Sale, Gift, Partition, Succession, ..."
    )
    executed_date: str | None = Field(
        description="The date the record gives for the transfer, as stated. A record that "
        "gives one date puts it here. Null when no date is stated."
    )
    registration_date: str | None = None
    transferors: list[Text] = Field(default_factory=list)
    transferees: list[Text] = Field(
        min_length=1, description="Who acquired the property. A transfer always names them."
    )
    property_schedule: str | None = None
    survey_number: str | None = None
    plot_number: str | None = None
    site_flat_number: str | None = None
    cts_number: str | None = None
    consideration: str | None = None
    summary_points: list[Text] = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)
    evidence_status: Literal[
        "corroborated", "register_reported", "deed_reported", "recital_reported"
    ] = Field(
        description="corroborated: two or more documents agree on it. "
        "register_reported: one history record reports it. "
        "deed_reported: only the transfer's own deed reports it. "
        "recital_reported: known only from the recital of a later deed."
    )


class ChainLink(_Strict):
    chain_position: int = Field(ge=1)
    continues_previous: bool = Field(
        description="True when this link's transferors are the acquirers of the link before "
        "it. False for the first link, and wherever the records leave a gap."
    )
    documented_transaction: DocumentedTransaction
    related_events: list[RelatedEvent] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _remove_empty_document_requests(cls, data: object) -> object:
        """Discard only an empty legacy field misplaced on a link by the model."""
        if isinstance(data, dict) and data.get("missing_documents") == []:
            return {key: value for key, value in data.items() if key != "missing_documents"}
        return data

    @model_validator(mode="before")
    @classmethod
    def _lift_nested_events(cls, data: object) -> object:
        """Accept ``related_events`` written inside the transaction by moving it to the link.

        Models often nest the events under the transaction they belong to. The
        meaning is unambiguous, so it is corrected here instead of costing a retry.
        """
        transaction = data.get("documented_transaction") if isinstance(data, dict) else None
        if not isinstance(transaction, dict) or "related_events" not in transaction:
            return data
        transaction = dict(transaction)
        nested = transaction.pop("related_events") or []
        return {
            **data,
            "documented_transaction": transaction,
            "related_events": [*(data.get("related_events") or []), *nested],
        }


class MissingDocument(_Strict):
    """A document that would extend the chain or close a gap in it."""

    document: Text = Field(description="What to upload, e.g. 'EC for 1994 to 2010'.")
    reason: Text = Field(description="What it would establish for this chain.")


class ChainResult(_Strict):
    """The complete result of one title-chain build."""

    property_identity: PropertyIdentity
    title_chain: list[ChainLink] = Field(min_length=1)
    missing_documents: list[MissingDocument] = Field(
        default_factory=list,
        max_length=0,
        description="Always empty. Document requests belong to verification, not chain building.",
    )

    @model_validator(mode="after")
    def _check_order_and_duplicates(self) -> ChainResult:
        positions = [link.chain_position for link in self.title_chain]
        if positions != list(range(1, len(positions) + 1)):
            raise ValueError(
                "chain_position must run 1, 2, 3, ... from the earliest transfer to the latest"
            )
        seen: set[str] = set()
        for link in self.title_chain:
            number = (link.documented_transaction.transaction_number or "").strip().casefold()
            if not number:
                continue
            if number in seen:
                raise ValueError(
                    f"duplicate transaction_number {number!r}: "
                    "one registered transfer is one chain link"
                )
            seen.add(number)
        for link in self.title_chain:
            label = link.documented_transaction.transaction_type
            if _NON_TRANSFER.search(label):
                raise ValueError(
                    f"link {link.chain_position} ({label}) is not an ownership transfer: record "
                    "it under related_events of the link whose owner it concerns"
                )
        latest: tuple[int, date] | None = None
        for link in self.title_chain:
            transaction = link.documented_transaction
            dated = parse_date(transaction.executed_date or transaction.registration_date)
            if dated is None:
                continue
            if latest and dated < latest[1]:
                raise ValueError(
                    f"title_chain must run from the earliest transfer to the latest: link "
                    f"{link.chain_position} is dated before link {latest[0]}"
                )
            latest = (link.chain_position, dated)
        return self

    def source_refs(self) -> Iterator[SourceRef]:
        """Every source reference in the result, wherever it appears."""
        for detail in self.property_identity.details:
            yield from detail.source_refs
        for link in self.title_chain:
            yield from link.documented_transaction.source_refs
            for event in link.related_events:
                yield from event.source_refs
