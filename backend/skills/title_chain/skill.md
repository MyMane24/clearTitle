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

This is a document investigation, not a legal opinion or a declaration that title
is legally clear.

## Permitted inputs

Use only the following document data retrieved from the database:

- Each document's stored summary.
- Each document's `merged_ocr_text`.

Do not use structured extraction JSON as evidence or as input to chain reasoning.
Do not assume facts that are absent from these inputs. Treat summaries as
navigation aids; use the relevant OCR text to establish material details.

Consider all uploaded files when looking for evidence, but retrieve and examine
documents as needed rather than assuming every document is relevant.

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
- Follow references to earlier instruments and transactions when available.
- Include a transaction mentioned in a recital even if its original instrument
  is not among the uploads. Mark that link as recital-reported / original deed
  not supplied; do not present it as directly verified by the missing deed.
- Represent each distinct recital-reported ownership transfer, succession, or
  partition as its own title-chain item and graph step. Do not collapse those
  links into a descriptive point on a later deed. Cite the document containing
  the recital, mark the link `recital_reported`, and leave unavailable dates or
  instrument numbers null.
- Use mutations and other records as evidence or corroboration, while keeping
  their role distinct from the underlying ownership instrument where applicable.
- Stop tracing when the available documents do not support the next link. Do not
  invent an owner, event, date, or missing connection. Keep the last supported
  link and its source clear in the graph and chain entries; do not add an
  `unresolved` field to property identity or chain entries.

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
available in supporting OCR. The transaction header contains only the
transaction/instrument number, transaction type, and execution date. Explain the
remaining material information as short, plain-language points, one fact per
point; do not use extracted field labels such as "Seller:" or "Consideration:".
Cover parties and roles, property conveyed, consideration, terms, conflicts, and
other material facts naturally. Do not put source references or filenames in
summary points. Keep source_refs separately at transaction/event level with the
document ID and filename only; filenames are citation metadata, not evidence.
Consolidate filenames in a Sources list after presenting the complete chain.
Keep points concise, avoid repetition, and use null for a missing transaction
number or date.

Do not fabricate page references. Do not merge conflicting values into one
apparently certain value; preserve the conflict and identify its sources.

## Result to produce

Produce these user-facing parts and structured chain data for later phases:

1. **Property being verified** — a concise list of the target property's
   supported identifying details.
2. **Title-chain graph** — a readable vertical graph ordered from the earliest
   supported root at the top, tracing forward through owners and events toward
   the current property owner at the bottom. Match the user's example's connected-node
   style, including event labels and dates between owners. Attach non-transfer
   events at the relevant point without presenting them as ownership transfers.
3. **Title-chain list** — one item per ownership link, in exactly the same order
   as the graph: earliest supported root first, then progressively forward, with
   the current/latest link last. Each item must preserve the full transaction
   details and source documents for later phases.

Use a connected vertical layout like this (actual output should include the
document-supported names, dates, references, property portions, and associated
events):

```text
EARLIEST OWNER(S) / ROOT
        │
        │ Earlier documented transfer or succession
        ▼
PRIOR OWNER(S)
        │
        │ Latest Sale Deed — date / registration reference
        ▼
CURRENT OWNER(S) / TARGET PROPERTY
```

For every `documented_transaction`, provide `transaction_number` (the explicit
registration/instrument reference, or null), `transaction_type`, `executed_date`
(or null), `summary_points` (an array of plain-language sentences), and overall
`source_refs`. Preserve all supported material details and uncertainty; do not
invent facts. During each period between ownership links, inspect relevant
documents for property events or developments. Put relevant non-transfer events
in `related_events`, each with its date/type, plain-language points, and separate
audit references. Do not include unrelated documents just to fill periods.

Do not produce a separate title story or chain summary. The graph, property
identity, and detailed title-chain list are the result; do not duplicate them in
a prose narrative.

The result must be self-contained and directly displayable by the frontend. The
frontend should render the agent's saved result rather than infer party roles,
transaction types, or property relationships itself.

## Required safeguards

- Property-schedule relevance governs whether an EC entry belongs to this chain.
- A recital is evidence that a document reports an earlier event, not proof that
  the original instrument was inspected.
- A mutation, conversion, permission, development event, or mortgage must not be
  mislabeled as a sale or other ownership transfer.
- Preserve uncertainty and conflicting descriptions in the relevant detail and
  evidence wording; do not add `unresolved` fields to property identity or chain
  entries.
- Never claim the chain is complete or title is clear solely because the supplied
  documents contain no contrary entry.
