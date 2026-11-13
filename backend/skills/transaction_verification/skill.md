# Transaction Verification Strategy

Use this skill when verifying one transaction in a Karnataka property title chain.

## How to use this skill

The task instructions script the workflow and the result format; this skill
supplies the type-specific verification strategy. Identify the transaction kind
and the type of property it conveys, apply the matching sections below together
with the general rules, and run each section's checks in order.

## General evidence rules

- Summaries are navigation aids only. Never verify from a summary, and never use
  structured extraction JSON as a substitute for the document's OCR.
- Use the upstream chain context returned by the application to avoid
  re-auditing completed links. Retrieve OCR for an earlier event only for a
  genuine dependency, newly supplied evidence or an explicit re-review.
- Verify, do not transcribe: the result reports checks and their outcomes (what
  the evidence proves, contradicts or leaves unestablished), never a retelling of
  the instrument's text.
- A candidate whose summary plausibly matches is selected and read in full before
  you decide it is missing or insufficient. Check alternate filenames before
  requesting anything, and never request a document already supplied under a
  different name. An uploaded copy is examined as is; mention certification only
  as a follow-up limitation when it matters.
- If metadata retrieval, OCR retrieval or persistence fails, treat the tool error
  as a failure and never infer the document's contents from its summary.
- When a transferor is a firm, company, trust or acts in a representative
  capacity, check the supplied evidence for the entity's existence, the
  signatory's capacity and the authority to convey, where material.
- A chain being property-specific does not make the property unchanged. A
  transfer A to B and B to C does not prove that a later flat sold by C is the
  same legally traceable interest in the original land; look for the documentary
  bridge and surface every unsupported step.

## Registration evidence outcomes

- Instrument found: examine it; report the registration particulars actually
  stated and whether each matches the title-chain claim.
- Registration mentioned elsewhere: report only what the inspected recital or
  document states. If the underlying instrument was not examined, do not claim it
  or its registration was independently verified.
- Instrument found, registration uncertain: state exactly which registration fact
  or status the supplied evidence does not establish.
- Instrument missing: request that specific instrument, set
  `PENDING_NOT_VERIFIED`, and do not infer invalidity from its absence.
- Conflicting particulars (number, date, office, parties): record the material
  conflict with references to both sources.

Where the evidence does not establish registration, say that registration remains
unverified and what is missing. Do not claim a registration authority was checked
unless a tool actually retrieved authoritative registration evidence. Registration
alone does not establish title. Do not call different registration numbers a
conflict unless the documents purport to identify the same instrument: a
declaration and a separate sale deed ordinarily carry distinct numbers, so explain
their relationship before alleging a mismatch. Distinguish OCR uncertainty from a
confirmed contradiction in the source documents.

## Strategy by transaction kind

### Sale, conveyance or other transfer for consideration

1. Identify transferors, transferees, the stated act, and the instrument,
   execution and registration particulars (number, dates, registering office,
   endorsements). A registration number in a recital is not independent proof of
   the referenced instrument's registration.
2. Compare the full schedule and conveyed share with the target property and with
   the neighbouring links; note changes in identifiers, area, boundaries or
   undivided shares without assuming they are equivalent.
3. Test the link in both directions: whether the transferor's supported interest
   covers what is conveyed, and whether the transferee's later transfer, if any,
   concerns the same property or share. Identify co-owners, partial shares,
   reservations, conditions and limits on authority.
4. Treat consideration and payment terms as documentary facts, not proof of title.
5. Distinguish an inspected instrument from details only recited in another deed.

### Gift, settlement or release

1. Confirm donor and donee (or releasor and beneficiary), their relationship where
   the deed states one, and that the instrument is registered and accepted or
   effective as the deed provides.
2. Check that the donor or releasor held the interest conveyed, including whether
   the gift or release covers only a share, and whether co-owners joined.
3. Note reservations, life interests, conditions, revocation clauses and any
   later cancellation. Consideration is usually nominal; its absence is not a
   defect.
4. For a release among co-owners, confirm which share moves to whom and that the
   parcel matches the chain.

### Succession, inheritance or will

1. Identify the deceased owner, the reported date of death, the claimed heirs,
   relationships, shares and the stated documentary basis.
2. Look for primary evidence of death, heirship and devolution (death certificate,
   legal-heir certificate, family tree, probated or registered will, court
   order). A mutation or khata entry corroborates; alone it does not prove
   inheritance.
3. For a will, check execution, attestation, probate or registration where
   stated, and whether all claimed heirs and shares reconcile.
4. Keep recital-reported succession explicitly qualified when primary evidence is
   absent, and request the missing record when it is material.

### Partition or family arrangement

1. Identify the parties and their existing interests, the nature and date of the
   arrangement, each party's allotment, and the supporting instrument or record.
2. Compare boundaries, survey or subdivision, area and shares before and after.
   A mutation entry alone does not prove a partition.
3. Distinguish an arrangement among owners from a later sale or flat conveyance;
   keep any mismatch or missing original unresolved.

### Power of attorney or authority to convey

1. Establish that the grantor held the interest, that the power covers this act,
   and that it was valid and in force on the execution date (registration,
   revocation, death or incapacity of the principal where the record shows it).
2. Check that the attorney's signature and capacity appear on the deed and that
   the deed recites the power correctly.

### Court order, decree or sale

1. Identify the court, case number, parties and date, and what the order
   actually directs.
2. Check that the order concerns this property and share, and whether a
   registered instrument or mutation followed where one is needed.

## Strategy by property type

### Land converted, laid out or developed into a project or apartments

When parent land becomes a layout, project or apartment building, verify the
documentary bridge:
- parent survey numbers and extent;
- the non-agricultural conversion order and permitted use, where relevant;
- the approved subdivision, layout or sanctioned building plan, as applicable;
- project land, and who had authority to develop and convey units;
- the exact flat, floor, schedule and undivided land share in the buyer's unit
  deed;
- RERA project registration, phase, status and extensions, and completion or
  occupancy information, where applicable.

Check whether each approval is applicable instead of assuming every project needs
every approval. A conversion order, plan approval, RERA record, khata, completion
record, power of attorney or apartment declaration is not itself proof of
ownership or of any other approval. Compare unit number, floor, area, parking,
PID or khata and schedule across the documents and preserve conflicting
measurements or identifiers. Flag a parent-land, project or unit mapping gap even
when the latest flat deed is registered. When a firm or other entity is the
developer or transferor, inspect available partnership or incorporation and
authority records that bear on its existence, signatories and capacity; a deed
naming an entity does not establish the signer's authority.

### Same house, flat or plot passing between owners

Test continuity and identity of that property across the deeds: same schedule,
extent, boundaries and unit details, and no unexplained change of identifier.

## Encumbrances and charges

- A mortgage, charge or lien is an encumbrance, not an ownership change.
- From the charge instrument identify borrower, lender, secured property,
  instrument and registration references, and any evidence of release, discharge
  or continuation. Record date or schedule discrepancies and their effect on the
  assessment.
- Never describe a charge as cleared without release evidence. When creation,
  property match or discharge is unsupported, report it as unresolved; do not infer
  its legal status from chain-discovery data alone.

## Administrative records

Mutation, conversion, permission, tax and khata records corroborate or document a
property event; they never create an ownership transfer on their own. Determine
what the record establishes, its date and authority, and how its property
description maps to the target. Examine one only when it is material to this
transaction, and never misclassify it as a conveyance.

## Current-owner endpoint records

For the last transaction, examine the records that show what the seller's title
carries, using only supplied non-EC documents:
- khata, PID, RTC or pahani: the named holder and whether the property
  description matches the schedule;
- property-tax receipts, demand and no-dues records: period covered, any unpaid
  or inconsistent amount;
- charge instruments and release, discharge or lender no-dues records, per the
  section above;
- utility, association or development dues only when the property type or the
  supplied records make them relevant;
- for an apartment or layout plot, the completion or occupancy record and
  building plan the latest deed relies on.

These records neither cure a broken chain nor independently establish ownership.
State the period each covers and any gap or inconsistency.

## Recital-reported links

- Verify exactly what the examined later document recites, and cite that
  document.
- State clearly that the underlying instrument was not examined; do not upgrade
  the link to an inspected or corroborated transaction.
- Request the underlying record only when it is material and absent; otherwise
  keep the limitation.

## Instrument and evidence quality

- Read all OCR chunks of each relevant instrument before a completed
  verification or a reported discrepancy. Look beyond the fields copied into the
  chain: recitals, the full schedule, conditions, exceptions, restrictions,
  corrections, cancellations and endorsements. Report an extra clause only when it
  is present in the reviewed text and affects this transaction, without turning
  ordinary legal wording into a defect.
- If OCR is truncated, contradictory, illegible or ambiguous, distinguish that
  insufficiency from a missing document and request a clearer or complete source
  when necessary. Cite the document ID and the page or section locator the tools
  provide; never invent page references.

## Guardrails

- An uploaded document marked skipped or unprocessed is not an absent document.
  Report that the existing upload could not be examined; do not request a
  duplicate.
- Distinguish an absent instrument from an uploaded but insufficient one. Missing
  or insufficient evidence is not evidence of a defect.
- Never label a transaction fraudulent, forged, invalid, or title clear without
  adequate basis.
