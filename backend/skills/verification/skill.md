# Playbook: Verify the title chain

Follow this playbook in every verification run. The topic playbooks after it
(title link, succession, partition, GPA and capacity, minors, encumbrances,
revenue records, land use and approvals) say what proves each kind of transfer.

> Draft structure. The legal content is to be confirmed and extended by the
> product owner's lawyer instructions (see specs/verification-agent/TASKS.md, 8.2).

## Goal

Prove that the current owner holds clear and marketable title: every transfer
from the root owner (30 years back) to the current owner is legally proved, each
one connects to the one before it, and nothing burdens the title.

## Method: one transfer at a time, oldest first

1. **Start.** Call `view_case_file` once. The chain marks the root ([ROOT]);
   links before it are outside the 30-year window and need no verdict. Examine
   every uploaded document in one turn: history documents (EC, mutation, RTC)
   and every deed, certificate, order and receipt. You need all of them to
   judge the transfers.
2. **Then, for each transfer from the root to the current owner, in order:**
   1. **Read the transaction.** From its chain entry and its own instrument:
      who transferred what to whom, when, how (sale, gift, partition,
      succession, release ...), and the property as the instrument describes it.
   2. **Property type and extent.** Note what was conveyed: agricultural land,
      converted plot, layout site, house, flat, commercial or other, and the
      extent.
   3. **Connection.** The transferors must be the previous transfer's acquirers,
      or people who stand in their place (heirs, a power of attorney holder, a
      successor company), shown by a document. The property must be the one
      the previous acquirer received: same survey or site number, extent not
      larger. If another step happened in between (a death, a partition, a
      release, a conversion), insert it with `insert_link` when any document
      reports it, and verify it first. Mark a break only when no document
      reports how ownership passed.
      **The root transfer** is verified on its own instrument only: its
      sellers' earlier title is outside the 30-year search, so never request
      documents older than the root.
   4. **Property type changed?** If the previous transfer conveyed agricultural
      land and this one conveys a site, house or flat, the land was converted,
      laid out or built on in between, even if no deed says so. Work out which
      steps happened and which documents prove each one (see
      `land_use_approvals`).
   5. **Decide which documents legally prove this transfer:** its own
      registered instrument, plus what the topic playbooks require for this kind
      of transfer and for any change of property type. For each one:
      - **uploaded:** reopen its examiner report (free) and confirm it really
        proves this transfer: the right parties, the right property and extent,
        the right date, registered or issued by the right authority. A document
        that does not match is a concern, not proof;
      - **not uploaded:** request it with `add_requisition`, one document per
        request, naming this transfer.
   6. **Verdict.** Record it with `record_link_verdict`: the property type and
      extent, every needed document as found (with citations) or missing (with
      its requisition), and a one- or two-sentence summary that names any concern
      or defect. Then move to the next transfer.
3. **After the last transfer: the whole property today.**
   - **Encumbrances:** every mortgage or charge has a matching release; the EC
     reaches the present day; attachments and pending cases are issues.
   - **Revenue records:** the RTC, mutation and khata follow the last transfer
     and name the current owner.
   - **Taxes and approvals:** property tax paid; the building, if any, has its
     approvals.
4. **Findings.** Record every problem a buyer must know about with
   `record_issue`, once each, in plain words, and what checked out with
   `record_clear_check` (owner name and survey number agree, EC reaches the
   present day, taxes paid). Keep each one to a short title and one or two
   short sentences.
5. **Close** when the "Still to do" line says nothing is left.

## Continued runs

When the Case File already has requests, first review the open ones: withdraw
every duplicate (keep one), every request for a document that is already
uploaded, and every request for title older than the root.

## Incremental runs

When documents arrive for requisitions, examine each new document, decide with
`review_requisition` whether it settles the requisition, then re-record the
verdict of every transfer it affects. Do not re-examine documents that did not
change.

## Safeguards

- Thirty years is a target, not a reason to invent links. What the documents do
  not show is a requisition or a limitation.
- A clear history entry is not proof of a transfer's validity; the instrument
  and the revenue records are.
- Never treat a nil or short encumbrance certificate as proof of no encumbrance.
- Never request a document that is already uploaded: examine it instead.
