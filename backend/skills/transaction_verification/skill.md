# Transaction Verification Strategy

Use this skill when verifying a transaction in a Karnataka property
title chain. It is a document-review procedure, not a legal opinion or a claim
that any document is genuine, valid, complete, or conclusive.

## Buyer-side objective

Support buyer-side due diligence by testing whether the active transaction and its
property-specific interest are supported within the available documentary chain.
The application has already reconstructed that chain and supplies one transaction
at a time; do not reconstruct it again or produce a case-wide report. Test relevant
 the active link without moving findings across transactions. Test
for breaks, overlapping or unexplained interests, authority/share problems, property-identity
drift, encumbrances, unpaid dues, and development/approval issues that could affect
a purchaser. Do not reduce the work to “a deed exists” or “names match.” State the
scope and dates of the records reviewed and the unresolved checks a buyer should
complete before purchase.

## Transaction verification: strategy by transaction type

For each active transaction, execute these steps in order:

1. Read its complete supplied title-chain object (ID/sequence, type, parties,
   dates, property/schedule, extent, consideration, registration details, related
   events, and all other available fields). These are claims to verify, not proof.
2. Use this and the relevant transaction-specific guidance to determine and record
   primary and supplementary document requirements; distinguish evidence of the
   transaction itself from evidence of related facts.
3. Search summaries through `list_documents`; it provides all case summaries for
   model-driven comparison. Compare them against the recorded evidence requirements
   and the active transaction's parties, dates, registration references, and property
   identifiers. Requirement-match hints are approximate discovery aids, not an
   exhaustive allow-list. You decide which documents actually match the required
   evidence; do not retrieve unrelated uploads merely because they are listed.
4. A keyword match or filename alone is not sufficient; decide whether each
   document's summary actually identifies needed evidence before selecting it.
   Structured extraction is not documentary evidence.
5. Select only matching required IDs and retrieve all chunks of each selected document's
    database-stored `merged_ocr_text`, following continuation/pagination parameters
    until the complete stored OCR has been read. Request `max_chars=200000` on the
    first OCR call; if `has_more` is true, continue at `next_start_char`.
6. Verify the transaction against full OCR and relevant supporting evidence,
   including full instrument contents and material recitals, schedules, conditions,
   exceptions, restrictions, corrections, cancellations, endorsements, clauses,
   and internal inconsistencies.
7. Produce one schema-valid result for the active transaction.
8. Persist under its existing stable ID and update compact workflow memory through
   the application's existing mechanisms.
9. Request evidence only after the database search and candidate inspection: if a
   matching uploaded document exists, inspect its complete OCR first. Request a
   document as missing only if no matching upload exists; if an inspected candidate
   is insufficient, request only what remains outstanding and explain the limitation.
   Keep each requirement attached to this active transaction, then use the existing
   pause/skip/resume workflow.

Never verify using summaries alone, use structured extraction JSON as a substitute
for documentary evidence, or claim a tool operation succeeded unless its output
confirms success. Examine adjacent transactions or related records only as needed
to understand the active transaction; keep its result limited to its own evidence.
Never infer legal validity merely from registration, mutation, or possession. The
EC is a Phase A chain-discovery source, not Phase B evidence; transaction
verification must use the underlying instrument and relevant supporting records.

Never retrieve or use another transaction's saved verification result. A source
document may describe an earlier event; examine that source itself and determine
its relevance to this active transaction. Do not create a finding or block this
transaction solely because another transaction is unresolved. Keep neutral facts
separate from adverse findings. Phase A may carry encumbrance facts forward as
related events. In Phase B, do not cite or describe those facts as EC entries; verify
the charge from its creation instrument and release/continuation evidence. Do not
assume a mortgage remains outstanding or assert legal effect without supporting
evidence.

The chain is property-specific but the property can evolve. Track land, portions,
plots, projects, buildings, flats, and undivided shares as distinct descriptions
unless the documents establish their relationship. A transfer from A to B and B
to C does not by itself prove that a later flat conveyed by C is the same legally
traceable interest in the original land. Look for the documentary bridge and
surface every unsupported step.

Never scan all case OCR to discover candidates. Search the uploaded-document list
and summaries/metadata for each requirement; a listed requirement is not proof that
it is absent. Check alternate filenames before requesting missing evidence. If a
matching summary exists, select that candidate and inspect its complete OCR before
deciding it is missing or insufficient. Do not request a document already supplied
under a different name; select and inspect it. Do not demand
certified copies when an uploaded copy can be examined; mention certification only
as a follow-up limitation when it matters.

For each candidate, use available metadata and summary to confirm it is plausibly
relevant, then use OCR to establish what the document actually says. If metadata
retrieval, OCR retrieval, or persistence fails, treat the tool error as a failure;
do not claim the operation succeeded or infer document contents from its summary.

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
  referenced instrument's registration. State registration as unverified where the
  available record does not establish it; do not imply a registrar/authority search.
- Apply these explicit outcomes:
  1. **Instrument found:** report registration particulars actually recorded in
     the examined instrument and whether they match the title-chain transaction.
  2. **Registration mentioned elsewhere:** report only what that inspected source
     states; the referenced instrument/registration remains unverified if it was not
     examined.
  3. **Instrument found, registration uncertain:** state exactly which registration
     status or particular the supplied evidence does not establish.
  4. **Instrument missing:** request that specific instrument and set
     `PENDING_NOT_VERIFIED`; absence is not evidence of invalidity.
  5. **Conflicting particulars:** record evidence-backed conflicts in numbers,
     dates, offices, parties, or other material registration details, citing each
     relevant source.
- Do not claim an authority search unless an available tool retrieves authoritative
  registration evidence. Registration alone does not establish title or validity.
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
- The EC is not supplied to Phase B. For the current/proposed seller, examine the
  underlying charge instrument and supplied lender/release/no-dues records. Report
  any charge whose creation, property match, or discharge remains unsupported as
  unresolved; do not infer its legal status from chain-discovery data alone.

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
  completed verification or material discrepancy finding. Inspect beyond fields
  copied into the title chain: recitals, full schedule, conditions, exceptions,
  restrictions, corrections, cancellations, endorsements, and other clauses that
  could affect this transaction.
- Identify an additional material clause only when it is present in the reviewed
  text; explain its relevance without turning ordinary legal wording into a defect.
- If OCR is truncated, contradictory, illegible, or ambiguous, distinguish that
  insufficient evidence from a missing document and request a clearer/complete
  source when necessary. Cite observed document ID and page/section locator where
  the OCR or retrieval tool provides one. Never invent page references.

## Completion and resume discipline

- Save one concise, schema-valid result for the active stable transaction ID:
  summary of what its own examined evidence establishes, material transaction-
  specific findings with observed document IDs/page references, reviewed document
  IDs, and only actionable outstanding requirements. Do not replace canonical
  evidence references with filenames, or include rule IDs, long OCR excerpts, or
  chain-of-thought.

- Verify one transaction at a time. Its saved structured result is the completion
  record; do not maintain a duplicate checklist.
- Use compact earlier-transaction checkpoints returned by the application to avoid
  re-auditing completed links. A checkpoint is not source evidence. Do not copy an
  earlier finding or its detailed discrepancy analysis into this transaction. When
  a prior result materially limits the active link, state the dependency once and
  reference its transaction ID; retrieve OCR only for a genuine dependency, new
  evidence, or explicit re-review.
- If essential evidence is missing, save a pending-not-verified result and the
  exact missing-document request against that transaction. Keep it resumable.
- Do not ask the user to upload a matching document that is already in the database.
  If an uploaded candidate is marked skipped/unprocessed, distinguish that from an
  absent document and report that the existing upload could not be examined; do not
  silently request a duplicate.
- Distinguish an absent instrument from an uploaded but insufficient instrument.
  Missing or insufficient evidence is not itself evidence of a defect. Follow the
  existing pause/skip workflow; after upload, reload and re-examine the same
  transaction, then upsert its existing result rather than assuming upload verifies
  it.
- If the user skips a request, leave that transaction pending/not verified and
  continue with other independent transactions. A later upload should resume the
  affected transaction unless new evidence materially changes another result.
- Do not duplicate an earlier transaction's finding in a later transaction result.
  Record only what the later transaction's own instrument establishes; where an
  upstream dependency limits it, state that limitation in transaction-specific
  terms without copying the prior finding.
- Every `required_documents` entry belongs to the active transaction ID. If the
  evidence is needed to verify a different chain transaction, leave it for that
  transaction's own result instead of attaching it here.
- Distinguish `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`,
  `INCONCLUSIVE`, and `PENDING_NOT_VERIFIED` according to the evidence. Never
  label a transaction fraudulent, forged, invalid, or title
  clear without adequate basis.
- Do not call two registration numbers a conflict unless both records purport to
  identify the same instrument. A declaration and a separate conveyance normally
  have separate registration numbers. Establish the instrument relationship first;
  report OCR ambiguity as uncertainty, not as a confirmed source-document conflict.
- Keep the result readable: lead with the active transaction's conclusion; include
  only material facts, precise evidence references, and actionable outstanding
  requirements. Target 100–180 words for the ordinary narrative (summary and
  findings), as guidance rather than a hard limit. Prefer a 1–2 sentence summary,
  up to three findings by default, and 1–3 sentences per finding. Add
  findings only for distinct material issues; do not omit material findings to hit
  the target. The summary is the conclusion, findings are the only detailed issue
  explanations, and required-document entries state the complete, specific document
  or record needed with a brief rationale. Preserve identifying dates, parties,
  registration references, and property identifiers needed to distinguish it.
  Required-document text is excluded from the narrative word budget and must never
  be abbreviated or truncated. Do not repeat a finding in the action section or
  repeat full deed recitals/another transaction's findings.
