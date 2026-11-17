# Skill: Build the title chain

Follow this skill every time a title chain is built or rebuilt.

## Goal

Show how the target property reached its current owner. Fix the property from
its latest sale, then trace its ownership backward, one transfer at a time, for
about thirty years. The result is a map for the verification stage, which later
checks each transfer against its own deed. Nothing here is verified yet, and it
is not a legal opinion.

## What you have

**History documents.** Read every one to the end.

- **Encumbrance certificate (EC)**: every registered transaction for the
  searched property and period, with date, registration number, parties and
  schedule. It is the backbone. It covers only its search period, and it does
  not show inheritance or other unregistered changes.
- **Mutation record, RTC (pahani)**: who was recorded as holder, when, and why
  the holder changed (sale, inheritance, partition, gift, grant). When
  uploaded, they supply the transfers the EC cannot show.

**Title deeds.** Listed with a short summary each. Open a deed for two reasons
only: to find how an owner got the property when the history records do not
say (step 4), or to settle a history entry that is unclear (step 5). You are
not verifying deeds; a later stage reads every one in full.

Records may be in Kannada or English, and one person's name is often spelled
differently across records. Treat two spellings as the same person only when
the records support it (same parent's or spouse's name, same property, same
instrument). Otherwise keep them apart and say so. Similar initials, surnames
or patronymics are clues to investigate in the deeds, not evidence of kinship
or inheritance. Even a stated family relationship does not by itself establish
an ownership transfer: find the recital describing how the property passed.

## Method

### 1. Read every history document to the end

Do this first. A chain built from a partly read record misses transfers.

### 2. Fix the target property from the latest sale

Find the latest sale recorded in the EC. Its purchasers are the current
owners, and its schedule is the target property.

- Record the property's identifiers in the record's own words: survey, plot,
  site, flat, PID, khata or CTS number, extent, village, hobli, taluk and
  boundaries.
- When the EC records no sale, use the latest ownership transfer it does
  record. When there is no EC, use the current holder in the latest revenue
  record. Say in the last link's summary points which one you used.

Stay on this property from here on. An entry belongs to the chain only when its
schedule is this property, or a larger property that the records show this one
was carved from. A record about a property you cannot connect to the target is
never a link: mention it in the summary points of the link it might explain,
and leave it out of the chain.

### 3. Trace backward through the history documents

Start from the latest sale and repeat:

1. Take the transferor of the current link.
2. Find how that transferor got this property: the nearest earlier record where
   they acquire it. Look in the EC first, then in the mutation record and RTC.
3. That record is the previous link. Make it the current link and repeat.

- **Unregistered transfers.** Inheritance, family partition and grant do not
  appear in the EC. Look for them in the mutation record and RTC, and in the
  recital of the next deed (step 4). Each is its own link; never fold it into
  the summary points of a neighbouring sale. For inheritance, put the date of
  death in the summary points when stated; the execution date stays empty
  unless the document dates an actual instrument.
- **A property that changed form.** A site may be carved from a larger survey
  number, or a house built on a plot. Follow the parent property only when the
  records connect the two (same survey number, a schedule that says "out of",
  matching extents or boundaries). Put the change on the link where it happens.
- **Several transferors.** Trace each one's share back. Their paths often meet
  at one earlier partition or inheritance.

### 4. Extend backward through the deeds

The history documents usually stop before thirty years, because the EC covers
a short period. When they do not say how the earliest owner got the property,
or leave a gap between two links, follow the deeds:

1. Take the link whose transferor's title is unexplained. Find its own deed in
   the title deed list by registration number, date and parties, and read it
   to the end.
2. Its recital says how the transferor got the property. Each step the recital
   reports (an earlier purchase, a partition, an inheritance) is its own
   earlier link, in order. Cite the deed you read and mark the link
   `recital_reported`. Leave null what the recital does not state.
3. When an earlier link's own deed is in the list, read it too. Take the
   link's details from it, cite it, and continue from its recital.
4. Repeat until the chain covers thirty years before the latest sale, or no
   deed is left to follow.

Before declaring an internal gap, read the later transfer's own uploaded deed
to the end, including its recitals and schedules. Follow every acquisition
step it reports and read the uploaded earlier deeds it points to. Review the
remaining deed summaries for other records that could explain the same gap;
read those deeds fully too. Summaries are a guide to opening documents, not
a substitute for their recitals. An absent earlier instrument does not prevent
a recital-supported link: cite the later deed and mark it `recital_reported`.

When a party on either side of the gap is a firm, company, association or
trust, read its constitution document from the deed list and identify its
partners, directors or trustees. If they are the same people who acquired the
property in the earlier link, the entity name is only those owners' collective
trading name: no transfer to the entity occurred, so the link continues, and
summary_points explains the entity's composition. A switch between individual
names and a firm name is not by itself an ownership gap. Keep the gap when the
entity's members are different owners or the constitution does not identify
them.

When no uploaded relevant deed remains to follow, record the unresolved gap
in the link's summary points. Do not request uploads in this phase.
Never invent an owner, a transfer or a date to reach thirty years.

### 5. Reconcile OCR and document conflicts before deciding continuity

You read OCR transcriptions, not the original scans. A deed's opening paragraph
can be corrupted even when its registration endorsements and signature blocks
are readable. Do not automatically prefer the first occurrence of a name, or
the OCR of an original deed over a clear recital in a later deed.

When a party, date or acquisition conflicts:

1. Read the relevant deeds fully. Compare the party introduction, operative
   transfer clause, purchaser/vendor signature labels, registration endorsements,
   schedules and acquisition recitals. Distinguish a power-of-attorney holder
   from the principal who acquires or conveys the property.
2. Establish whether the passages describe the same transaction using its
   registration number, date, seller and property portion, extent and boundaries.
   Shared property alone does not establish shared ownership.
3. Compare later acquisition recitals with those internal passages. When readable
   endorsements or signatures support the identity explicitly reported in matching
   later recitals, use that supported identity for the single transfer. Do not
   create another owner or a missing transfer from an isolated garbled name.
   Explain the conflicting OCR wording, the adopted reading and its documentary
   basis in summary_points; cite every document used to reconcile it.
4. If the available passages do not resolve the conflict, retain the competing
   readings and an unresolved gap. Do not choose a name merely because it makes
   the chain connect, because initials match, or because several later deeds
   repeat a claim. Never invent an alias or a family relationship.

For example, an opening paragraph names an unclear buyer, but the purchaser
signature and registration endorsement identify a representative of A. B. Rao,
and a later deed identifies Arun B. Rao as purchaser under that same registration,
date and parcel. This supports a single purchase by Arun, with an OCR discrepancy
note. Conversely, a clear purchase by Arun followed by a sale by different people
who merely cite Arun's purchase does not establish inheritance or a transfer
to those people; that acquisition remains unexplained.

A clear EC transfer is enough for a `register_reported` link. Do not require
its own deed merely to confirm its parties or details; the verification stage
handles instrument requirements. Open that deed only when its recitals can
explain an acquisition or its text can settle an actual ambiguity.

### 6. Keep non-transfers out of the chain

- Mortgage, deposit of title deeds, release of mortgage, lease, sale agreement,
  power of attorney and attachment do not change ownership. Record each as a
  related event on the link of whoever owned the property at that time. A
  lender is never an owner.
- Conversion to non-agricultural use and layout or building approvals are
  related events too.
- Leave out entries for other properties. One registration number is one link:
  merge duplicate entries and duplicate copies of a record.

### 7. Check the chain

- **Recital completeness.** Reconcile the acquisition recitals of every deed
  you read against the links. An earlier purchase or an effective bequest
  described in a recital must be its own `recital_reported` link even when
  its original instrument is absent. Do not bury it in a later sale's notes
  or say it is unsupported merely because its own deed was not uploaded.
  A will's execution date is not the date ownership passed on death; leave
  the transfer date null when the recital does not state it.
- **Parcel-specific partition.** Record the allottee of the portion leading
  to the target property as its acquirer, not every participant receiving
  other portions. Explain the other allotments in summary points if useful.
- **Owner mismatch.** Compare each link's transferors with the preceding
  acquirers after the OCR reconciliation in step 5. Distinguish two readings
  of the same purchaser from genuinely different owners. For genuinely different
  owners, find the intervening transfer; a reference to the earlier registration
  number alone does not explain their acquisition. Preserve a gap only after
  checking the available internal passages and later recitals.
- **Continuity.** The transferor of each link must be the acquirer of the link
  before it. Where that holds, mark the link as continuing the previous one.
  Where it fails, do not add a connecting transfer: mark the link as not
  continuing and state the gap in its summary points.
- **Every link is a real transfer** of the target property and names who
  acquired it.
- **Support.** Mark each link by how it is known:
  - `corroborated`: two or more documents agree on it (EC and mutation, or EC
    and the deed).
  - `register_reported`: one history record reports it.
  - `deed_reported`: only the transfer's own deed, which you read, reports it.
  - `recital_reported`: only the recital of a later deed reports it.
- **Naming.** Name each link by what the record shows, with fitting roles:
  sale (seller, purchaser), gift (donor, donee), partition (parties,
  allottees), succession (deceased owner, heirs), release, court decree,
  grant. Record the kind of property each link transfers.
- **Current holder.** When the latest RTC or mutation names a
  holder other than the purchasers of the latest sale, say so in the last
  link's summary points.

### 8. Record unresolved limits

Build the strongest supported chain from the uploaded records. Thirty years
is a tracing target, not an upload requirement or a reason to reject a shorter
chain. After exhausting relevant uploaded deeds, state any unresolved change
of ownership or limited historical coverage in the affected link's summary
points. Leave `missing_documents` empty. Document requests belong to the later
verification stage, not this reconstruction.

### 9. Write the result from earliest to latest

You traced backward; the result runs forward, in date order. The first link is
the earliest transfer you reached and the last link is the latest sale from
step 2. Nothing comes after it.

## Safeguard

Never state or imply that the chain is complete, or that title is clear,
because the records show no contrary entry. Absence of an entry is not
evidence of a clean chain.
