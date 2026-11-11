"""Add the evidence PA-TC-0001 demanded on DEMO-CLEAN-001 (round 2).

The verify loop paused on the KUDA root asking for the five authority-side
records the deed recites: acquisition record, layout sanction order, conversion
order, allotment letter and possession certificate. This seeds all five with
content consistent with every number already in the chain documents.
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 env var exists on this machine and setdefault would silently target the stale local MySQL

from backend.database.connection import _get_conn  # noqa: E402
from backend.database.repositories.document_repo import (  # noqa: E402
    init_document,
    update_document_status,
)

CASE_ID = "DEMO-CLEAN-001"

ACQUISITION = """KARNATAKA URBAN DEVELOPMENT AUTHORITY, BELAGAVI
RECORD OF LAND ACQUISITION — HONAGA EXTENSION RESIDENTIAL SCHEME

1. PRELIMINARY NOTIFICATION
No. KUDA/LAQ/PR-141/1992 dated 12-08-1993 — intention to acquire the lands of
Survey No. 45 (Sy. Nos. 45/1, 45/2 and 45/3), Honaga Village, Belagavi Taluk
and District, for the Honaga Extension Residential Scheme, under Section 28 of
the Karnataka Urban Development Authorities Act, 1987. Published in the
Karnataka Gazette, Part IV-2C, dated 26-08-1993.

2. FINAL DECLARATION
No. KUDA/LAQ/FD-143/1993 dated 07-02-1994 — the following lands stand declared
acquired for the scheme:
   Survey No. 45/1 — 7930 square metres
   Survey No. 45/2 — 12140 square metres (subsequently developed as Block 'A'
                     and Block 'B', 6070 sq m each)
   Survey No. 45/3 — 1100 square metres (reserved as park under the layout)
   Total — 21170 square metres

3. AWARD AND COMPENSATION
Award No. 3/1994-95 dated 28-06-1994 passed by the Special Land Acquisition
Officer, KUDA Belagavi. Total compensation of Rs. 9,52,650/- was paid in full
to the pattadars (landowners) on 14-07-1994 vide challans
Nos. 1147, 1148 and 1149 of the State Bank of Mysore, Honaga Branch.

4. POSSESSION
Physical possession of the acquired land was taken over by the Authority on
30-07-1994 in the presence of the Tahsildar, Belagavi, and entrusted to the
Engineering Division for scheme development.

ACQUISITION STATUS: Complete. No acquisition proceedings are pending and no
litigation is on record in respect of the acquired lands.

Signed: Special Land Acquisition Officer, KUDA Belagavi, 15-08-1994"""

LAYOUT_SANCTION = """GOVERNMENT OF KARNATAKA
HOUSING AND URBAN DEVELOPMENT DEPARTMENT

ORDER No. HUD/24/KUD/94
Bengaluru, dated: 04-11-1994

SUBJECT: Sanction of the layout plan of the "Honaga Extension Residential
Scheme" of the Karnataka Urban Development Authority, Belagavi.

READ: KUDA letter No. KUDA/BS/HON/33/1994 dated 09-09-1994 and the Detailed
Scheme Report.

GOVERNMENT ORDER:
The layout plan of the KUDA Honaga Extension Residential Scheme over the
acquired lands of Survey No. 45 (total 21170 sq m) of Honaga Village, Belagavi
Taluk, comprising 24 residential sites (Site Nos. 1 to 24), one park and
internal roads, is hereby sanctioned, subject to the scheme conditions of the
Karnataka Urban Development Authorities Act, 1987 and the KUDA (Sites)
Allotment Rules.

ANNEXURE (EXTRACT OF SITE LIST):
   Site No. 13 — Survey No. 45/2, Block 'A' — area 6070 sq m — residential
   Site No. 14 — Survey No. 45/2, Block 'B' — area 6070 sq m — residential
   Site No. 15 — Survey No. 45/1 — area 7930 sq m — residential

The Authority shall execute conveyance deeds in favour of allottees under
Section 26 of the Act on full payment of site value.

By order and in the name of the Governor of Karnataka,
Under Secretary to Government, Housing and Urban Development Department.
Copy to: The Commissioner, KUDA Belagavi, for compliance and publication."""

CONVERSION = """ORDER No. ALN/CR/45/1994-95
OFFICE OF THE DEPUTY COMMISSIONER, BELAGAVI
Dated: 19-12-1994

SUBJECT: Conversion of land from agricultural to non-agricultural
(residential) purposes — Survey No. 45/1 and Survey No. 45/2 (Block 'A' and
Block 'B'), Honaga Village, Belagavi Taluk and District.

WHEREAS the Karnataka Urban Development Authority, Belagavi has applied for
conversion of the lands described below for its sanctioned Honaga Extension
Residential Scheme (layout sanctioned vide Government Order No. HUD/24/KUD/94
dated 04-11-1994);

UNDER SECTION 95 OF THE KARNATAKA LAND REVENUE ACT, 1964, the lands described
below are converted from agricultural to residential use, on payment of the
conversion fine of Rs. 63,510/- (challan dated 16-12-1994):

   Survey No. 45/1 — 7930 square metres — converted residential
   Survey No. 45/2, Block 'A' — 6070 square metres — converted residential
   Survey No. 45/2, Block 'B' — 6070 square metres — converted residential

CONDITIONS:
1. The land shall be used strictly in accordance with the sanctioned layout.
2. No further subdivision shall be made without the approval of the
   competent authority.
3. Other conditions of the KLR Act and rules shall apply.

Signed: Deputy Commissioner, Belagavi."""

ALLOTMENT = """KARNATAKA URBAN DEVELOPMENT AUTHORITY, BELAGAVI

ALLOTMENT LETTER No. KUDA/HON/A-2213/1994
DATED: 12-01-1996

SUBJECT: Allotment of Site No. 14 under the Honaga Extension Residential
Scheme, Belagavi.

Sri Ningappa Chanaveer Kulkarni, S/o Chanaveer Kulkarni, Honaga Village,
Belagavi Taluk, is hereby allotted the following site under the KUDA (Allotment
of Sites) Rules:

   Site No. 14 — Survey No. 45/2, Block 'B'
   Area: 6070 square metres (1 Acre 20 Guntas)
   Tentative price: Rs. 85,000/- (Rupees Eighty Five Thousand only)

PAYMENT: The full site value stands paid by the allottee vide challans dated
22-01-1996 and 27-02-1996 (Rs. 42,500/- each) through the State Bank of Mysore,
Honaga Branch.

The allottee accepted the allotment on 20-01-1996.

CONDITIONS:
(a) The site shall be used only for the purpose shown in the sanctioned layout.
(b) Construction shall conform to the scheme bye-laws.
(c) Betterment charges, if levied later, shall be payable by the allottee.
(d) Conveyance (Allotment-cum-Sale Deed) shall be executed under Section 26 of
    the KUDA Act, 1987, on the terms of this allotment.

Signed: Competent Authority, KUDA Belagavi."""

POSSESSION = """KARNATAKA URBAN DEVELOPMENT AUTHORITY, BELAGAVI

POSSESSION CERTIFICATE No. KUDA/HON/P-2213/1996
DATED: 20-02-1996

CERTIFIED that physical possession of the following site of the Honaga
Extension Residential Scheme, Honaga Village, Belagavi Taluk and District, was
handed over to the allottee on 18-02-1996, in the presence of the Executive
Engineer and the Junior Engineer of the Authority:

   Allottee: Sri Ningappa Chanaveer Kulkarni, S/o Chanaveer Kulkarni
   Site No.: 14
   Survey No.: 45/2, Block 'B' (6070 sq m — 1 Acre 20 Guntas)

BOUNDARIES AS PER THE SANCTIONED LAYOUT:
   North: Land of Sidagouda Patil
   South: Honaga-Degulhalli Road
   East: Land of Rudragouda Yarakannavar
   West: Land of Shivayogi Mudenur

The allottee has signed the handover proceedings held on the site.

Signed: Executive Engineer, KUDA Belagavi Division."""

DOCUMENTS = (
    ("DOC-ACQ-1994", 6, "KUDA_LandAcquisitionRecord_1993-1994.pdf", "OTHER_DEED",
     ACQUISITION,
     "KUDA land acquisition record for Survey No. 45, Honaga: preliminary "
     "notification 12-08-1993, final declaration 07-02-1994, award 3/1994-95, "
     "compensation paid, possession taken 30-07-1994 — establishes KUDA's title "
     "and authority to convey."),
    ("DOC-GO-1994", 7, "LayoutSanctionOrder_HUD-24-KUD-94.pdf", "OTHER_DEED",
     LAYOUT_SANCTION,
     "Layout sanction Order HUD/24/KUD/94 dated 04-11-1994 — Government approves "
     "the KUDA Honaga Extension scheme; annexure maps Site No. 14 to Survey "
     "No. 45/2B, 6070 sq m."),
    ("DOC-CONV-1994", 8, "DC_ConversionOrder_ALN-CR-45-1994-95.pdf", "OTHER_DEED",
     CONVERSION,
     "Conversion Order ALN/CR/45/1994-95 dated 19-12-1994 — Deputy Commissioner "
     "converts Survey No. 45/1 and 45/2 (Blocks A and B) from agricultural to "
     "residential under Section 95, KLR Act."),
    ("DOC-ALLOT-1996", 9, "KUDA_AllotmentLetter_A-2213-1994.pdf", "OTHER_DEED",
     ALLOTMENT,
     "KUDA allotment letter KUDA/HON/A-2213/1994 dated 12-01-1996 — Site No. 14 "
     "(Survey No. 45/2B, 6070 sq m) allotted to Ningappa Chanaveer Kulkarni for "
     "Rs 85,000, fully paid."),
    ("DOC-POS-1996", 10, "KUDA_PossessionCertificate_P-2213-1996.pdf", "OTHER_DEED",
     POSSESSION,
     "KUDA possession certificate KUDA/HON/P-2213/1996 dated 20-02-1996 — "
     "possession of Site No. 14 (Survey No. 45/2B) delivered to Ningappa "
     "Chanaveer Kulkarni on 18-02-1996."),
)


def main() -> None:
    for doc_id, idx, filename, doc_type, text, summary in DOCUMENTS:
        init_document(case_id=CASE_ID, doc_id=doc_id, doc_index=idx,
                      filename=filename, expected_type=doc_type)
        update_document_status(
            case_id=CASE_ID, doc_id=doc_id, status="structured",
            document_type=doc_type, merged_ocr_text=text, summary=summary,
            page_count=2,
        )
    with _get_conn() as conn:
        conn.cursor().execute(
            "UPDATE cases SET total_docs = %s WHERE id = %s",
            (6 + len(DOCUMENTS), CASE_ID))
        conn.commit()
    print(f"Added {len(DOCUMENTS)} evidence documents to {CASE_ID} "
          f"(total {6 + len(DOCUMENTS)}).")


if __name__ == "__main__":
    main()
