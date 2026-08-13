# Legal Opinion Report — Format Draft

> Draft for preview. Dynamic fields are shown as `{{ placeholders }}`.
> Final output: PDF (A4, formal letterhead style), generated from structured data
> produced by the clearTitle pipeline (sale deed, EC, RTC, conversion order, etc.).

---

## Page 1 — Letterhead + Subject

```
┌────────────────────────────────────────────────────────────────┐
│   [LOGO]                                    clearTitle®         │
│                                                                 │
│   <Advocate / Firm Name>                       Office Ph: ...   │
│   B.Com., LL.B. (Spl)                          Mobile: ...      │
│   ADVOCATE                                     EmailID: ...     │
│   <Office Address line 1>                                       │
│   <Office Address line 2, CITY-PIN>                             │
├────────────────────────────────────────────────────────────────┤
│   Date : {{ 12.08.2026 }}                                       │
│                                                                 │
│   To,                                                           │
│   WHOM SO EVER IT MAY CONCERN                                   │
│                                                                 │
│   Sub : Legal opinion in respect of {{ R.S.No. 590/2 }}         │
│         held by {{ Shri. Ramesh S/o Narasingasa Chavan }}       │
│                                                                 │
│   With reference to the above, the legal opinion is furnished   │
│   as under:                                                     │
└────────────────────────────────────────────────────────────────┘
```

---

## Section I — Names of the Owner(s) as per the Record

| # | Property | Owner as per Record |
|---|----------|---------------------|
| 1 | {{ Survey no. + extent }} | {{ Owner name (S/o …) }} |
| 2 | {{ Survey no. + extent }} | {{ Owner name (S/o …) }} |

---

## Section II — Parties Who Should Sign the Sale Deed / Agreement

**For Property {{ # }}**

| # | Party | Role |
|---|-------|------|
| 1 | {{ Name, S/o … }} | Vendor / First Party |
| 2 | {{ Name, S/o … }} | Consenting Witness |
| 3 | {{ Major family members … }} | Consenting Witness |

> If more than one property, repeat the above block per property.

---

## Section III — Description of the Properties Considered for Verification

### Property No. {{ 1 }} — held by {{ Ramesh S/o Narasingasa Chavan }}

- **Classification:** {{ NA residential open land }}
- **Survey No.:** {{ R.S.No. 590*/2 }}
- **Extent:** {{ 28 Gunta }}
- **Situation:** {{ Unkal Village of Hubli City and Taluk }}

**Boundaries:**

| Direction | Boundary |
|-----------|----------|
| East      | {{ Adjacent Hissa No. 1 }} |
| West      | {{ Adjacent R.S.No. 589 }} |
| North     | {{ Road }} |
| South     | {{ Adjacent Hissa No. 3 }} |

> Repeat this block for each property (2, 3, … n).

---

## Section IV — List of Documents Produced for Perusal

> Populated from the case's structured documents, ordered by date.

| Sl.No. | Particulars | Date | Remarks |
|-------:|-------------|------|---------|
| 1 | {{ Record of Rights Form No. 6, ME No. 8284 of R.S.No. 590/2 & 591/1 }} | {{ 11.08.2011 }} | {{ Xerox Copy }} |
| 2 | {{ Registered Sale Deed by … in favour of … doc. No. 1766 }} | {{ 20.06.2002 }} | {{ Original verified }} |
| … | … | … | … |

**Remarks vocabulary:** Original verified · Xerox Copy · Certified Copy · Online Certified Copy

---

## Section V — Tracing of Title for the Last {{ 46 }} Years

> Narrative derived from the title chain — each numbered point maps a
> document from Section IV to a link in the ownership chain.

1. {{ SI.No. 1 discloses that the original owner … expired on {{ date }} leaving behind … as legal heirs … }}
2. {{ SI.No. 2 discloses that … }}
3. {{ SI.No. 3 is the registered sale deed … in favour of {{ Ramesh }} … thus {{ Ramesh }} became the absolute owner. }}
4. {{ SI.No. 4 … subdivision of R.S.No. 590/2 into 590*/2 and 590*/3 … }}
5. {{ … }}

---

## Section VI — Encumbrances

{{ The encumbrance certificates referred at Sl.No. {{ 15 to 20 }} disclose that the property is free from encumbrance. }}

---

## Section VII — Minor's Claim / Interest, if any

{{ Nil }}

---

## Section VIII — Details of Liability / Restrictive Covenants and Safeguards

{{ Nil }}

---

## Section IX — Application of ULC Act

{{ Not applicable }}

---

## Section X — List of Documents to be Collected by the Branch

| Sl.No. | Particulars | Date | Remarks |
|-------:|-------------|------|---------|
| 1 | {{ … }} | {{ … }} | {{ Original }} |
| … | … | … | … |

---

## Section XI — Additional Documents to be Taken

{{ Nil }}

---

## Section XII — Final Certificate (Conclusion)

> Auto-generated verdict from the verification pass (clear / clear with
> observations / not clear), with reason.

{{ I am therefore of the considered opinion that {{ R.S.No. 590*/2 and 591*/1 }}
held by {{ Shri. Ramesh S/o Narasingasa Chavan }} and {{ R.S.No. 590*/3 }}
held by {{ Shri. Sunil S/o Narasingasa Chavan }} have acquired a clear,
legal and marketable title to the said property and the same is fit for
intending purchaser. }}

Thanking you,

Yours faithfully,

<br><br><br>

```
                      ______________
                      ({{ N.S. Bhat }})
                      {{ B.Com., LL.B. (Spl) }}
                      {{ Advocate, Hubli }}
```

---

## Formatting Notes (for PDF generation)

- **Paper:** A4 portrait, ~2 cm margins.
- **Header:** Firm logo + name + contact block on every page.
- **Subject line:** Bold, underlined.
- **Section headings:** Roman numerals (I–XII), bold, all caps.
- **Document table:** full-width, thin borders, small font (9–10pt), allow row-splitting across pages with repeated header row.
- **Boundary tables:** 2-column, compact.
- **Signature block:** right-aligned, leave 3 blank lines above the name.
- **Multi-property case:** Sections I, II, III repeat per property; title tracing (V) is one consolidated narrative.
