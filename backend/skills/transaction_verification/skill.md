# Transaction Verification Strategy

Use this skill when verifying a transaction in a Karnataka property title chain.

## How to use this skill

The task instructions script the verification workflow. This skill supplies the
type-specific verification strategy for it. Apply the section below that matches
the active transaction type, together with the general rules here, and execute
each section's checks in the order given.

## General evidence rules

Never verify using summaries alone or use structured extraction JSON as a
substitute for documentary evidence. Verify the active transaction on its own
instrument plus only the documents it uniquely depends on: a recital describing
an upstream chain transaction points to an already-verified upstream result,
never to re-reading that upstream instrument; at a root transaction the
vendors' own pre-chain title documents recited by the instrument (a prior deed,
a will) are this transaction's evidence; other transactions' instruments and
later chain events stay with their own verifications. Keep the result limited
to the active transaction's own evidence. Never infer legal
validity merely from registration, mutation, or possession. When a transferor is
a firm, company, trust, or representative capacity, check the supplied evidence
for entity existence, signatory capacity, and authority to convey where material.
The chain being property-specific does not make the property unchanged: a
transfer from A to B and B to C does not by itself prove that a later flat
conveyed by C is the same legally traceable interest in the original land —
look for the documentary bridge and surface every unsupported step.

Verify, do not transcribe: the result reports checks and their outcomes — what
the evidence proves, contradicts, or leaves unestablished — never a retelling
of the instrument's text, and never narration of which documents were selected
or skipped.

Never scan all case OCR to discover candidates. Check alternate filenames before
requesting missing evidence. If a matching summary exists, select that candidate
and inspect its complete OCR before deciding it is missing or insufficient. Do
not request a document already supplied under a different name; select and
inspect it. Do not demand certified copies when an uploaded copy can be
examined; mention certification only as a follow-up limitation when it matters.

For each candidate, use available metadata and summary to confirm it is plausibly
relevant, then use OCR to establish what the document actually says. If metadata
retrieval, OCR retrieval, or persistence fails, treat the tool error as a failure
and never infer document contents from its summary.

## Registration evidence outcomes

- Instrument found: examine the corresponding instrument; report the registration
  particulars actually stated and whether each available particular matches the
  title-chain claim.
- Registration mentioned elsewhere: report only what the inspected recital/document
  states. If the underlying instrument was not examined, do not claim that
  instrument or its registration was independently verified.
- Instrument found, registration uncertain: state exactly which registration
  fact/status is not established by the supplied evidence.
- Instrument missing: request that specific instrument, set `PENDING_NOT_VERIFIED`,
  and do not infer invalidity from its absence.
- Conflicting particulars: record material conflicts (number, date, office,
  parties, or other particulars) as evidence-backed report statements with
  references to the relevant sources.

Whenever the available evidence does not establish registration, state that
registration remains unverified and identify what is missing or uncertain. Do not
claim that a registration authority was checked unless an available tool actually
retrieves authoritative registration evidence. Registration alone does not
establish title or legal validity. Do not call different registration numbers a
conflict unless the documents purport to identify the same instrument. A
declaration and a separate sale deed ordinarily have distinct registration
numbers; explain their relationship before alleging a number mismatch.
Distinguish OCR uncertainty from a confirmed source-document contradiction.

## Strategy by transaction type

### Sale, conveyance, gift, release, or other transfer

- Identify transferor(s), transferee(s), the stated act, instrument/date and
  registration particulars where present.
- Compare the complete schedule and conveyed share with the target property and
  preceding/succeeding chain links; note changes in identifiers, area, boundaries,
  or undivided shares without assuming they are equivalent.
- Check what the cited evidence says about the transferor's interest or authority
  and the transferee's acquisition. Treat consideration and payment terms as
  documentary facts, not proof by themselves of title.
- Distinguish an inspected instrument from details only recited in another deed.
- Compare the transaction's stated registration number, registration/execution
  dates, registering office, and available endorsements against the instrument.
  A registration number mentioned in a recital is not independent proof of the
  referenced instrument's registration.
- Apply the Registration evidence outcomes above to this transaction's
  registration particulars.
- Inspect the deed, transferor-interest/authority evidence, parcel/share match,
  and only transaction-specific material events or encumbrances.
- Test the chain link in both directions: whether the transferor's supported
  interest covers what is conveyed, and whether the recipient's later transfer
  (if any) concerns the same property/share. Identify co-owners, partial shares,
  reservations, conditions, or authority limitations that could affect the buyer.

### Succession, inheritance, or death-related devolution

- Identify the deceased owner, reported date, claimed successors, relationship,
  shares, and stated legal/documentary basis.
- Look for the source evidence supporting death, heirship, and devolution. A
  mutation/name entry is corroborative record
  evidence; do not treat it alone as conclusive proof of inheritance or title.
- Keep recital-reported succession explicitly qualified when primary evidence is
  absent; identify the missing record when material to the case assessment.
- Check the case-specific material questions (death, successor identity, claimed
  share, or parcel continuity) and request essential evidence if it is missing.

### Partition, family arrangement, or allocation

- Identify parties and their existing interests, the nature/date of the
  arrangement, the specific allotment to each party, and the supporting
  instrument or record.
- Compare boundaries, survey/subdivision, area, and shares before and after the
  arrangement. Do not assume a mutation entry itself proves a partition.
- Distinguish an arrangement among owners from a later sale or apartment
  conveyance; retain any mismatch or missing original instrument as unresolved.
- Check material interest/allocation, schedule/boundary, and corroborating records
  where applicable.

### Apartment declaration, development, construction, or unit allocation

- Check the link between parent land, project/building, unit identifier, undivided
  land share, and the later unit conveyance.
- Identify who had authority to develop or convey units and what each document
  actually does. A power of attorney, building permission, completion record, or
  declaration is not automatically an ownership transfer.
- Compare unit number, floor, area, parking, PID/khata and schedule across the
  documents; preserve conflicting measurements or identifiers.
- Check development/conveyance authority and project-to-unit mapping when the
  transaction raises them.
- Where agricultural or other parent land becomes a layout/project/apartment,
  verify the available documentary bridge: parent survey numbers and extent;
  non-agricultural conversion order and permitted use where relevant; approved
  subdivision/layout or sanctioned building plan as applicable; project land and
  development/conveyance authority; and the exact flat, floor, schedule, and
  undivided land share in the buyer's unit deed. Consider RERA project registration,
  project phase, status/extensions, and completion information where applicable.
  Check applicability rather than assuming RERA or a particular approval is
  required in every case. A conversion order, plan approval, RERA record, khata,
  completion/occupancy record, or apartment declaration is not itself proof of
  ownership or of every other approval. Flag a parent-land/project/unit mapping
  gap even if the latest flat sale deed is registered.
  If a firm or other entity is named as transferor/developer, inspect available
  partnership/incorporation and authority records when they bear on the entity's
  existence, partners/signatories, or capacity to execute the active instrument.
  A deed naming an entity does not by itself establish the signer's authority.

### Mortgage, charge, or other encumbrance

- Treat it as an encumbrance, not an ownership-changing transaction.
- Identify borrower, lender, secured property, instrument/deposit date and
  registration reference from the charge instrument, and any evidence of release
  or continuation.
- Record date or schedule discrepancies and the effect on the title-chain
  assessment. Do not describe an encumbrance as cleared without release evidence.
- Check the relevant creation instrument, property match, and release or
  continuation evidence where applicable.
- For the current/proposed seller, examine the underlying charge instrument and
  supplied lender/release/no-dues records. Report any charge whose creation,
  property match, or discharge remains unsupported as unresolved; do not infer
  its legal status from chain-discovery data alone.

### Mutation, conversion, permission, tax, or other administrative record

- Determine what the record establishes, its date/authority, and how its property
  description maps to the target. Treat it as corroboration or a property event
  unless the evidence establishes a different legal effect.
- Do not create an ownership transfer solely from an administrative entry.
- Examine an administrative record only when material to this transaction; never
  misclassify it as a conveyance.
- At the current-owner endpoint, review supplied current property-tax receipts,
  demand/arrears or no-dues records, and khata/PID/RTC or equivalent records when
  relevant to the property type and jurisdiction. State the period covered and any
  unpaid or inconsistent amount/identity. These records are administrative or
  corroborative; they do not cure a broken title chain or independently establish
  ownership. Association, utility, or other dues should be raised only when the
  property type or supplied records make them relevant.

### Recital-reported link (any type)

- Verify exactly what the examined later document recites and cite that document.
- State clearly that the underlying event's original instrument/record was not
  examined. Do not upgrade the link to an inspected or independently corroborated
  transaction. Request specific missing evidence only when it is material to the
  assessment; otherwise preserve the limitation.
- Distinguish confirming what a recital says from inspecting the underlying
  original/certified record. Request that record if essential and absent.

### Full instrument and evidence quality

- Read all OCR chunks for each relevant selected instrument before making a
  completed verification or reporting a material discrepancy. Inspect beyond fields
  copied into the title chain: recitals, full schedule, conditions, exceptions,
  restrictions, corrections, cancellations, endorsements, and other clauses that
  could affect this transaction.
- Identify an additional material clause only when it is present in the reviewed
  text; explain its relevance without turning ordinary legal wording into a defect.
- If OCR is truncated, contradictory, illegible, or ambiguous, distinguish that
  insufficient evidence from a missing document and request a clearer/complete
  source when necessary. Cite observed document ID and page/section locator where
  the OCR or retrieval tool provides one. Never invent page references.

## Discipline guardrails

- Use the upstream chain context returned by the application to avoid re-auditing
  completed links; retrieve OCR only for a genuine dependency, new evidence, or
  explicit re-review.
- If an uploaded candidate is marked skipped/unprocessed, distinguish that from
  an absent document and report that the existing upload could not be examined;
  do not silently request a duplicate.
- Distinguish an absent instrument from an uploaded but insufficient instrument;
  missing or insufficient evidence is not itself evidence of a defect.
- Never label a transaction fraudulent, forged, invalid, or title clear without
  adequate basis.
