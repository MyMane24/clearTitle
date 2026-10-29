# Skill: Build the target property's title chain

## When to use this skill

Load and follow this skill every time the agent builds or rebuilds a property's
title chain. Do not substitute a generic title-chain prompt for it. If the skill
cannot be loaded, do not silently build the chain using incomplete instructions.

## Purpose

Identify the target property from the latest sale deed(s) in the case and trace
the property's ownership history backward through relevant uploaded documents.
Produce a property identity and a traceable, property-specific title-chain graph
with transaction details supported by the available evidence.

Trace the chain as far back as the uploaded evidence supports. Title
investigation practice expects roughly the last 30 years to be covered; when the
documents do not reach that far, record the earliest supported root explicitly
as the chain limit rather than inventing earlier links. Keep that earliest
supported root as the first chain item and state the limitation in its summary
points.

This is a document investigation, not a legal opinion or a declaration that title
is legally clear.

## Permitted inputs

Use only each document's stored summary and `merged_ocr_text` retrieved from the
database. Treat summaries as navigation aids; use the relevant OCR text to
establish material details.

## Procedure

### 1. Establish the target property

1. Find the latest sale deed or deeds in the uploaded set and inspect their OCR.
2. Identify the property conveyed and the current purchaser(s), preserving the
   wording and distinctions present in the document.
3. Record all useful property identifiers and descriptions, for example flat,
   building, floor, local property number, PID, survey number, plot number,
   portion, extent, undivided share, parking, and location.
4. Preserve differences in identifiers over time. Do not silently treat similar
   numbers or descriptions as identical; explain the documentary basis for a
   match in the relevant identity detail or chain entry.

### 2. Filter EC entries for this property

1. Read the EC OCR and inspect its transaction entries.
2. Compare each entry's property schedule/details with the target property
   established from the latest sale deed.
3. Use relevant matching identifiers, portions, schedules, and documented links
   to decide whether an entry relates to the target property.
4. Include or use only relevant entries. Never copy every EC transaction into
   the title chain just because it appears in the EC.
5. Exclude entries for other properties. If relevance is uncertain, record the
   uncertainty instead of treating the entry as a confirmed link.

The EC is a source of leads and corroboration; it is not, by itself, the title
chain.

### 3. Trace ownership backward

Starting from the latest purchaser and target property, follow relevant sale
deeds, EC entries, recitals, and other uploaded documents backward through the
ownership history. At each link:

- Identify who held or claimed the relevant property or share before the event.
- Identify who received, inherited, was allotted, or otherwise acquired it.
- Match the property or conveyed portion to the target property using the
  document evidence.
- Track property evolution separately from ownership transfer. A parent
  agricultural survey parcel may later be converted, subdivided, laid out,
  developed, and represented by one or more buildings/flats. Preserve these as
  dated property events and show the documentary links between the parent parcel,
  resulting project/plot, and exact later unit/share. Do not silently treat land,
  a project, and a flat as the same unchanged asset or as separate unrelated
  assets; establish the relationship from schedules, survey references, extents,
  approvals, plans, and other available records, and mark gaps explicitly.
- Follow references to earlier instruments and transactions when available.
- Include a transaction mentioned in a recital even if its original instrument
  is not among the uploads; mark it `recital_reported` per the task's chain
  completeness rule rather than presenting it as directly verified.
- Use mutations and other records as evidence or corroboration, while keeping
  their role distinct from the underlying ownership instrument where applicable.
- Stop tracing when the available documents do not support the next link; do not
  invent an owner, event, date, or missing connection.

### 4. Classify events and label parties correctly

Do not force every event into `seller` and `buyer`. Use roles appropriate to the
documented event, such as transferor/transferee, donor/donee, deceased owner/heir,
partitioning parties/allottees, releasing party/beneficiary, or mortgagor/lender.

Distinguish ownership-changing links from other property events. For example,
non-agricultural conversion, building permission, development, partnership
formation, apartment declaration/allocation, and mortgage/deposit of title deeds
are not automatically ownership transfers. Show such events at the relevant
point in the graph with the responsible owner or parties and the supported
details. Represent a mortgage or other charge as an encumbrance, not as a new
owner.

Choose transaction/event labels that accurately describe the evidence. Do not
assign a transaction type merely to fit a predefined seller/buyer model.

### 5. Capture transaction details and evidence

For every chain link or associated event, capture all relevant details actually
available in supporting OCR, following the field and style rules in the task
instructions. Do not fabricate page references. Do not merge conflicting values
into one apparently certain value; preserve the conflict and identify its sources.

## Result to produce

Produce the structured result specified in the task instructions: the target
property's supported identifying details, a connected vertical title-chain graph
ordered from the earliest supported root to the current owner, and a title-chain
list in the same order with full transaction details and source documents for
later phases. The result must be self-contained and directly displayable by the
frontend, which renders the saved result rather than inferring party roles,
transaction types, or property relationships itself.

## Required safeguards

- Never claim the chain is complete or title is clear solely because the supplied
  documents contain no contrary entry; absence of evidence is not evidence of a
  clean chain.
