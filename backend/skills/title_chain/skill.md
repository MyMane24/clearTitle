# Skill: Build the target property's title chain

Follow this skill every time a title chain is built or rebuilt. If it cannot be
loaded, do not build the chain from partial instructions.

## Goal

Identify the target property from the latest sale deed(s) and trace its ownership
backward, link by link, to the earliest supported root. The result lets a buyer
see how the property reached the proposed seller, and lets later stages verify
each link on its own. It is a document reconstruction, not a legal opinion.

Cover roughly the last 30 years of title, as far back as the uploads support.
When they do not reach that far, keep the earliest supported root as the first
chain item and state in its summary points that earlier records were not
available. Never invent earlier links.

## Method

### 1. Establish the target property

1. From the summaries, find the latest sale deed(s) and read their OCR. If no
   sale deed exists, use the latest supported conveyance as a provisional
   endpoint and state that limitation instead of asserting a current owner.
2. Identify the property conveyed and the current purchaser(s), keeping the
   document's own wording.
3. Record every useful identifier: flat, building, floor, PID, khata, survey
   number, plot or site number, portion, extent, undivided share, parking,
   boundaries, location.
4. Keep identifiers that differ across documents as differences. Match
   similar-looking ones only when you can state the documentary basis for the
   match.

### 2. Filter EC entries for this property

The EC discovers and orders transfers and encumbrances; it is not itself the
chain.
- Include an entry only when its schedule matches the target property by
  identifiers, portion or a documented link. Exclude other properties' entries.
  When relevance is uncertain, record the uncertainty instead of a confirmed
  link.
- Represent each relevant transfer as its own chain item and each non-transfer
  encumbrance as a related event, stating the transaction or event itself. Do
  not write "the EC lists" or label anything an "EC entry"; the EC appears only
  in `source_refs`, as audit provenance.

### 3. Trace ownership backward

From the latest purchaser, follow sale deeds, EC leads, recitals and other
uploads backward. At each link establish who held the interest before, who
acquired it and by what act, and that the conveyed portion matches the target
property. Follow references to earlier instruments when available.

- Every distinct ownership-changing link the evidence reports is its own chain
  item, including links reported only in a later deed's recital. Never fold a
  prior sale, inheritance, succession or partition into the summary points of a
  later deed.
- Use mutations and other administrative records as corroboration, distinct from
  the underlying ownership instrument.
- Consolidate duplicate copies of one registered instrument into a single item;
  never list one registration number twice.
- Stop when the documents do not support the next link. Do not invent an owner,
  event, date or connection.

### 4. Classify each link by transfer kind and property type

Name each link by what the evidence shows, with roles that fit the act: sale
(transferor/transferee), gift (donor/donee), partition or family arrangement
(parties/allottees), succession or inheritance (deceased owner/heirs), release
(releasor/beneficiary), will, or court order. Do not force every event into
seller and buyer.

Track the type of property conveyed by each link: agricultural land, converted
site or plot, layout, building, apartment unit with undivided share, or a house
or flat passing unchanged. When a later link conveys a different type than the
earlier ones, record the change on that later link.

Keep ownership transfers apart from property events. Conversion to
non-agricultural use, layout or building approval, development, partnership
formation, apartment declaration or allocation, and mortgage or deposit of title
deeds are not ownership transfers. Show them as related events at the right
point, with the responsible parties and supported details; a mortgage or charge
is an encumbrance, never a new owner. Where agricultural land became a layout,
project and then a flat, show the dated events and the documentary links between
parent parcel, resulting plot or project, and the exact later unit and share;
establish the relationship from schedules, survey references, extents and
approvals, and mark gaps explicitly. Do not treat land, project and flat as
either the same unchanged asset or unrelated assets.

For a succession link, keep the deceased owner's date of death in the summary
points; `executed_date` stays null unless an actual succession instrument has a
stated execution date.

### 5. Record details and conflicts

Capture the details the OCR actually supports, following the task's field
rules. Do not fabricate page references. Where documents give conflicting values,
keep both and identify the sources instead of merging them into one certain value.

### 6. Check the endpoint before saving

The final chain item must be the latest sale identified in step 1: it cites that
deed, gives its registration or instrument number and execution date when
stated, and ends with the documented purchaser(s) as current owner(s). The graph
must end at the same purchaser(s). When the latest deed is uploaded in several
copies, use the clearest OCR and cite the document ID(s) you actually examined.

## Safeguard

Never state or imply that the chain is complete or that title is clear because
the documents contain no contrary entry. Absence of evidence is not evidence of a
clean chain.
