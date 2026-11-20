# Playbook: Verify the title chain

Follow this playbook in every verification run, with the topic playbooks after
it (title link, succession, partition, GPA and capacity, minors, encumbrances,
revenue records, land use and approvals) where the case needs them.

> Draft structure. The legal content is to be confirmed and extended by the
> product owner's lawyer instructions (see specs/verification-agent/TASKS.md, 8.2).

## Goal

Establish whether the current owner holds clear and marketable title to the
target property, by verifying each transfer in the chain against its own
evidence for about thirty years, and by finding anything that could defeat or
burden that title.

## Method

1. **Start.** Call `view_case_file` once to see the chain and documents. Read
   only what verifying the transactions needs; decide from the document
   summaries, never by reading everything.
2. **History documents first.** Examine every encumbrance certificate, mutation
   record and RTC. Ask the examiner for every transfer, mortgage, release,
   attachment and change of holder, with dates and parties.
3. **Compare with the chain.** For each history entry and each recital that
   touches the target property, find its link. Missing transfer reported by any
   document (including a succession shown by death and family or legal-heir
   certificates): insert it, then judge its evidence in the verdict. Wrong
   details: correct the link. An owner change that no document reports at all:
   open a lead, and after exhausting the documents, mark the break.
4. **Each link's own instrument.** Examine the deed of each transfer, asking for
   vendors and their capacity, the schedule and extent, registration and stamp
   duty, consideration, and the vendor's source of title. Apply the title-link
   playbook and any topic playbook the transfer needs (succession, partition,
   GPA and capacity, minors).
5. **Follow every lead.** Examine the documents that can settle it. If none is
   uploaded, add a requisition that names the lead in `closes_leads`.
6. **Encumbrances.** Every mortgage or charge needs a
   matching release; every attachment or pending case is an issue.
7. **Revenue records.** The RTC and mutation records
   should follow each transfer; the current holder should be the current owner.
8. **Land use and approvals.** Check these when the property is
   or was agricultural land, a layout site, or a building.
9. **Verdicts.** Record a verdict for every link. A link whose own instrument is
   missing is `unverified_missing_document` with a requisition naming it.
10. **Close.** When the latest "Still to do" says nothing is left, give your
    closing summary.

## Incremental runs

When documents arrive for requisitions, examine each new document, decide with
`review_requisition` whether it settles the requisition, then update every
link, lead and issue it affects. Re-record the verdict of an affected link.
Do not re-examine documents that did not change.

## Safeguards

- Thirty years is a target, not a reason to invent links. Record what the
  documents do not show as a limitation or requisition.
- A clear history entry is not proof of a transfer's validity; the instrument
  and revenue records are.
- Never treat a nil or short encumbrance certificate as proof of no encumbrance.
