# Transaction Verification Strategy

Use this skill when verifying a transaction in a Karnataka property
title chain. It is a document-review procedure, not a legal opinion or a claim
that any document is genuine, valid, complete, or conclusive.

## Buyer-side objective

Answer whether the available documentary evidence supports the proposed seller's
identity as the current title holder and interest in the exact property being considered, traced backward through every
supported transfer to the earliest available mother-title/root. Test for breaks,
overlapping or unexplained interests, authority/share problems, property-identity
drift, encumbrances, unpaid dues, and development/approval issues that could affect
a purchaser. Do not reduce the work to “a deed exists” or “names match.” State the
scope and dates of the records reviewed and the unresolved checks a buyer should
complete before purchase.

## Transaction verification: strategy by transaction type

For each transaction selected by the orchestrator, use the transaction-verification
prompt, this skill, saved document summaries for navigation, and the relevant database-stored
`merged_ocr_text` as evidence. Structured extraction is not evidence. Examine the
transaction in the context of the adjacent chain links and target property. Record
what the evidence does and does not establish; never infer legal validity merely
from registration, mutation, possession, or absence of an EC entry.

The chain is property-specific but the property can evolve. Track land, portions,
plots, projects, buildings, flats, and undivided shares as distinct descriptions
unless the documents establish their relationship. A transfer from A to B and B
to C does not by itself prove that a later flat conveyed by C is the same legally
traceable interest in the original land. Look for the documentary bridge and
surface every unsupported step.

First read the transaction and this skill, then decide and record the
transaction-specific evidence requirements. Only after that, inspect the short
document summaries, select likely relevant document IDs, and retrieve full OCR for
those selected documents. Never scan all case OCR to discover candidates. Check
uploaded filenames and document summaries before requesting missing evidence. Do
not request a document already supplied under a different name; select and inspect
it. Do not demand certified copies when an uploaded copy can be examined; mention
certification only as a follow-up limitation when it matters.

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

### Mortgage, charge, or other encumbrance

- Treat it as an encumbrance, not an ownership-changing transaction.
- Identify borrower, lender, secured property, instrument/deposit date and
  registration/EC references, and any evidence of release or continuation.
- Record date or schedule discrepancies and the effect on the title-chain
  assessment. Do not describe an encumbrance as cleared without release evidence.
- Check the relevant creation instrument, property match, and release or
  continuation evidence where applicable.
- For the current/proposed seller, examine the available EC and other supplied
  lender/release/no-dues records over their stated dates and property scope. Report
  each live, unlinked, or inadequately discharged charge as a buyer risk. Never
  infer that no loan or lien exists solely because an EC is blank, incomplete, or
  covers a limited period.

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

## Completion and resume discipline

- Save a short result: one-sentence conclusion, 2–5 concise factual finding
  points, sources named by their uploaded PDF filenames, and only genuinely
  missing evidence. Do not expose internal IDs, rule IDs, OCR excerpts, or long
  chain-of-thought in the user-facing result.

- Verify one transaction at a time. Its saved structured result is the completion
  record; do not maintain a duplicate checklist.
- If essential evidence is missing, save a pending-not-verified result and the
  exact missing-document request against that transaction. Keep it resumable.
- If the user skips a request, leave that transaction pending/not verified and
  continue with other independent transactions. A later upload should resume the
  affected transaction unless new evidence materially changes another result.
- Distinguish `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`,
  `INCONCLUSIVE`, and `PENDING_NOT_VERIFIED` according to the evidence. Never
  label a transaction fraudulent, forged, invalid, or title
  clear without adequate basis.
