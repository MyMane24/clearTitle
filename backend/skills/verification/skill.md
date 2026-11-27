# Playbook: Verify the title chain

Follow this playbook in every verification run. The topic playbooks after it
(title link, succession, partition, GPA and capacity, minors, encumbrances,
revenue records, land use and approvals) say what proves each kind of transfer.

> Draft structure. The legal content is to be confirmed and extended by the
> product owner's lawyer instructions.

## Goal

Prove the title: every transfer from the root owner (30 years back) to the
current owner is legally proved and connects to the one before it, and no
charge of an earlier owner was left unreleased when the property passed on. A
charge that still subsists against the present owner is disclosed in the
report, not treated as a defect.

## The result: one record per transfer

For each transfer you record what proves it, how it connects to the transfer
before, and what is wrong with it. The application turns that into the result
(verified, verified with concerns, waiting for documents, defective), the
requests to the buyer and the title report. Example:

```
2008 sale, Ramesh to Suresh, Sy. 45/2, 2 acres, agricultural land
connects:  no: the 1995 buyer was Ramappa, not Ramesh
documents: found   registered sale deed of 2008 (cited)
           missing legal-heir certificate of Ramappa: shows Ramesh is his heir
           missing death certificate of Ramappa: shows he died before 2008
concerns:  none beyond the missing documents
summary:   Registered sale, but nothing yet shows how Ramesh got the land from Ramappa.
-> waiting for documents; two requests to the buyer
```

## Method

1. **Read.** Call `view_case_file` once. The chain marks the root ([ROOT]);
   transfers before it are outside the 30-year search and need no record.
   Examine every uploaded document in one turn: history documents (EC,
   mutation, RTC) and every deed, certificate, order and receipt.
2. **Fix the chain.** Compare every recital and history entry with the
   transfers. If a document reports a step the chain lacks (a death, a
   partition, a release, a conversion), insert it with `insert_transfer`
   before verifying anything after it. A step the chain already has with
   wrong details is corrected when you record it, not inserted again. Remove duplicates and entries for
   another property with `remove_transfer`.
3. **Verify each transfer, from the root to the current owner, in order:**
   1. **Read the transaction** from its own instrument: who transferred what
      to whom, when, how (sale, gift, partition, succession, release ...).
   2. **Property:** survey or site number, extent, and type (agricultural
      land, converted plot, layout site, house, flat, commercial, other).
   3. **Connection:** the transferors must be the previous transfer's
      acquirers, shown by a document, and the property the one they received
      (same survey or site number, extent not larger). When someone stands in
      their place (heirs, a successor company), that step is a transfer of
      its own: insert it. **A death certificate, a family or legal-heir
      certificate or a will that shows the sellers inherited is a succession
      to insert, never a break;** list on the succession any heirship document
      still missing. Record `connects` false only when no document shows how
      ownership passed. **The root** is verified on its own instrument
      only: never request documents older than the root.
   4. **Property type changed?** If the previous transfer conveyed
      agricultural land and this one conveys a site, house or flat, the land
      was converted, laid out or built on in between. Work out which documents
      prove each step (see `land_use_approvals`) and list them.
   5. **Documents:** list every document that legally proves this transfer:
      its own registered instrument, plus what the topic playbooks require.
      An uploaded document is found only after you confirm it proves this
      transfer (right parties, property, extent, date, registration); cite
      it. One that is not uploaded is missing.
   6. **Concerns:** every problem, once, with its severity, on the transfer
      where it arises. A concern never just says a document is missing: the
      missing document already says that.
   7. **Record** it all in one `record_transfer` call, then move on.
4. **The property today** (`record_property_today`, after the last transfer):
   - **encumbrances:** a mortgage or charge of an earlier owner was released
     before the property passed to the next owner; the EC reaches the present
     day; attachments and pending cases are concerns. A charge that still
     subsists against the present owner is stated in the note, not recorded as
     a concern: the report discloses it.
   - **revenue_records:** the RTC, mutation and khata follow the last
     transfer and name the current owner.
   - **tax_and_approvals:** property tax paid; conversion, layout and
     building approvals where the property needs them.
5. **Unexpected findings:** cite each one in a record, or set it aside with
   a reason it does not affect title.
6. **Close** when the "Still to do" line says nothing is left.

## When documents arrive

Examine each new document, then record again every transfer (or part of the
property today) its request is for: found if it proves what was needed,
still missing if it does not. Do not re-examine documents that did not change.

## Safeguards

- Thirty years is a target, not a reason to invent transfers. What the
  documents do not show is a missing document or a concern.
- A clear history entry is not proof of a transfer's validity; the instrument
  and the revenue records are.
- Never treat a nil or short encumbrance certificate as proof of no
  encumbrance.
- Never list as missing a document that is already uploaded: examine it.
