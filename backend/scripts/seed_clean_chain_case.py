"""Seed a fresh demo case (DEMO-CLEAN-001) whose title chain is CLEAN.

Six documents, all mutually consistent, so the agent should end with a valid
title: a KUDA allotment-cum-sale deed (chain root, 1996) -> sale 2004 ->
sale 2013 -> sale 2024 to the current owner, plus a 32-year EC recording
exactly those four entries and an RTC showing the 2024 mutation in the current
owner's name. Pure conveyances: no mortgage, no minors, no agreements to sell.

Idempotent: only rows of DEMO-CLEAN-001 are touched. The agent is NOT started
here; run backend/scripts/run_clean_case_phases.py for the A->B->C->D run.
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 env var exists on this machine and setdefault would silently target the stale local MySQL

from backend.database.connection import _get_conn  # noqa: E402
from backend.database.repositories.case_repo import init_case, update_case_status  # noqa: E402
from backend.database.repositories.document_repo import (  # noqa: E402
    init_document,
    update_document_status,
)

CASE_ID = "DEMO-CLEAN-001"

PROPERTY_SCHEDULE = """All that land measuring 6070 square metres (1 Acre 20 Guntas), being Survey No. 45/2B (Old Survey No. 45/2, Block 'B'), Situated at Honaga Village, Belagavi Taluk and District, Karnataka, and bounded on:-
North: Land of Sidagouda Patil
South: Honaga-Degulhalli Road
East: Land of Rudragouda Yarakannavar
West: Land of Shivayogi Mudenur"""

SCHEDULE_BLOCK = (
    "SCHEDULE OF PROPERTY\n" + PROPERTY_SCHEDULE + "\n"
)

DEED_1996 = """KARNATAKA URBAN DEVELOPMENT AUTHORITY, BELAGAVI

ALLOTMENT-CUM-SALE DEED
(Executed under the Karnataka Urban Development Authorities Act, 1987)

EXECUTED ON: 08-03-1996
REGISTERED IN: Office of the Sub-Registrar, Belagavi
BOOK NO. 1, DOCUMENT NO. BLG-1-341/1995-96

BETWEEN

KARNATAKA URBAN DEVELOPMENT AUTHORITY (K.U.D.A.),
represented by its Competent Authority, Honaga Extension Division, Belagavi,
(hereinafter referred to as "THE VENDOR / THE AUTHORITY", which expression shall
include its successors and assigns)

AND

SRI NINGAPPA CHANAVEER KULKARNI, aged about 41 years, S/o Chanaveer Kulkarni,
Resident of Honaga Village, Belagavi Taluk and District, Karnataka.
(hereinafter referred to as "THE ALLOTTEE / PURCHASER")

WHEREAS the Authority acquired and developed the land of the "K.U.D.A. Honaga
Extension Residential Scheme, Belagavi" under its layout plan sanctioned by the
Government of Karnataka vide Order No. HUD/24/KUD/94 dated 04-11-1994;

AND WHEREAS the said layout comprising residential sites in Survey No. 45 of
Honaga Village was converted from agricultural to residential use by the Deputy
Commissioner, Belagavi vide Conversion Order No. ALN/CR/45/1994-95 dated
19-12-1994;

AND WHEREAS the site described in the Schedule hereunder was allotted to the
Allottee vide Allotment Letter No. KUDA/HON/A-2213/1994 dated 12-01-1996 at a
tentative price of Rs. 85,000/- (Rupees Eighty Five Thousand only);

AND WHEREAS the Allottee has paid the full site value together with development
charges, and physical possession of the site was delivered to the Allottee vide
Possession Certificate No. KUDA/HON/P-2213/1996 dated 20-02-1996;

AND WHEREAS under Section 26 of the Karnataka Urban Development Authorities
Act, 1987 the Authority is competent to convey absolute title to allottees upon
full payment of the site value;

NOW THIS DEED WITNESSES AND IT IS HEREBY AGREED AND DECLARED AS FOLLOWS:

1. In consideration of the site value of Rs. 85,000/- (Rupees Eighty Five
Thousand only) paid in full by the Allottee, the Authority hereby grants,
conveys and transfers by way of absolute sale all its right, title and
interest in the Schedule Property unto the Allottee, to hold the same
absolutely and forever.

2. The Authority declares that the Schedule Property is free from all
encumbrances, claims and demands whatsoever, and that it has not entered into
any agreement to sell, mortgage, lease or exchange in respect of the Schedule
Property with any other person.

3. The Allottee shall thereafter be liable for the municipal taxes, betterment
charges (if any levied) and maintenance charges in respect of the Schedule
Property.

""" + SCHEDULE_BLOCK + """
IN WITNESS WHEREOF the Competent Authority of the Karnataka Urban Development
Authority, Belagavi has hereunto set his hand on the date first above written.

Signed for and on behalf of K.U.D.A. Belagavi:
S.G. Noolkar, Competent Authority

WITNESSES:
1. M.I. Prabhu, Executive Engineer, K.U.D.A. Belagavi
2. V.S. Nadaf, Accounts Officer, K.U.D.A. Belagavi

Stamp duty of Rs. 4,250/- and registration fee of Rs. 850/- paid by demand
draft. Registered in Book No. 1, Document No. BLG-1-341/1995-96 on 08-03-1996
before the Sub-Registrar, Belagavi."""

DEED_2004 = """SALE DEED
(Deed of Absolute Conveyance)

EXECUTED ON: 15-07-2004
REGISTERED IN: Office of the Joint Sub-Registrar, Belagavi
BOOK NO. 1, DOCUMENT NO. BLG-2-511/2004

BETWEEN

SRI NINGAPPA CHANAVEER KULKARNI, aged about 49 years, S/o Chanaveer Kulkarni,
Resident of Honaga Village, Belagavi Taluk and District, Karnataka,
(hereinafter referred to as "THE VENDOR")

AND

SRI MAHADEV NINGAPPA KULKARNI, aged about 35 years, S/o Ningappa Chanaveer
Kulkarni, Resident of Fort Road, Belagavi,
(hereinafter referred to as "THE PURCHASER")

WHEREAS the Vendor is the absolute owner of, and stands possessed of, the
Schedule Property, having acquired the same from the Karnataka Urban
Development Authority, Belagavi, vide Allotment-cum-Sale Deed dated 08-03-1996,
registered in Book No. 1 as Document No. BLG-1-341/1995-96 of the Office of the
Sub-Registrar, Belagavi;

AND WHEREAS the Vendor has been in open, continuous and undisturbed possession
of the Schedule Property since such acquisition, paying all taxes and
outgoings;

AND WHEREAS the Vendor, being in need of funds for his family obligations, has
offered to sell the Schedule Property to the Purchaser, and the Purchaser has
agreed to purchase the same for a total sale consideration of Rs. 6,50,000/-
(Rupees Six Lakhs Fifty Thousand only);

AND WHEREAS the entire sale consideration has been paid by the Purchaser to the
Vendor by demand draft No. 441502 dated 14-07-2004 drawn on Canara Bank,
Belagavi Branch, the receipt whereof the Vendor hereby acknowledges;

NOW THIS DEED WITNESSES AND IT IS HEREBY AGREED AND DECLARED AS FOLLOWS:

1. The Vendor hereby grants, conveys and transfers by way of absolute sale
unto the Purchaser, all that the Schedule Property together with all rights,
easements and appurtenances thereto, to hold the same absolutely and forever.

2. The Vendor declares that the Schedule Property is free from all
encumbrances and that he has not entered into any agreement to sell,
mortgage, lease or gift in respect thereof with any other person, and if any
such claim arises the Vendor shall alone be liable to make good the loss to
the Purchaser.

3. The physical possession of the Schedule Property is handed over to the
Purchaser today, and the Purchaser shall pay the taxes and outgoings from the
year 2004-05 onwards.

4. The Vendor shall always stand by to confirm this transfer, and shall sign
and execute such further writings as may be necessary at the cost of the
Purchaser.

""" + SCHEDULE_BLOCK + """
IN WITNESS WHEREOF the Vendor has hereunto set his hand on the day and year
first above written.

VENDOR: Ningappa Chanaveer Kulkarni
PURCHASER: Mahadev Ningappa Kulkarni

WITNESSES:
1. Shivayogi Mudenur, S/o Fakirappa Mudenur, Honaga Village
2. Anand S. Deshpande, Advocate, Belagavi

Stamp duty of Rs. 45,500/- and registration fee of Rs. 6,500/- paid. Registered
in Book No. 1, Document No. BLG-2-511/2004 on 15-07-2004 before the Joint
Sub-Registrar, Belagavi."""

DEED_2013 = """SALE DEED
(Deed of Absolute Conveyance)

EXECUTED ON: 05-11-2013
REGISTERED IN: Office of the Joint Sub-Registrar, Belagavi
BOOK NO. 1, DOCUMENT NO. BLG-3-876/2013

BETWEEN

SRI MAHADEV NINGAPPA KULKARNI, aged about 44 years, S/o Ningappa Chanaveer
Kulkarni, Resident of Fort Road, Belagavi,
(hereinafter referred to as "THE VENDOR")

AND

SRI GANGADHAR MAHADEV KULKARNI, aged about 33 years, S/o Mahadev Ningappa
Kulkarni, Resident of Fort Road, Belagavi,
(hereinafter referred to as "THE PURCHASER")

WHEREAS the Vendor is the absolute owner of, and stands possessed of, the
Schedule Property, having acquired the same under Sale Deed dated 15-07-2004,
registered in Book No. 1 as Document No. BLG-2-511/2004 of the Office of the
Joint Sub-Registrar, Belagavi, from one Ningappa Chanaveer Kulkarni;

AND WHEREAS the Schedule Property has been enjoyed by the Vendor openly,
continuously and undisturbedly since such acquisition, without any
encumbrance whatsoever;

AND WHEREAS the Vendor has offered to sell the Schedule Property to the
Purchaser for a total sale consideration of Rs. 18,50,000/- (Rupees Eighteen
Lakhs Fifty Thousand only), and the Purchaser has agreed to purchase the same;

AND WHEREAS the entire sale consideration of Rs. 18,50,000/- has been paid by
the Purchaser to the Vendor by demand draft No. 701263 dated 04-11-2013 drawn
on State Bank of Mysore, Belagavi Main Branch, the receipt whereof the Vendor
hereby acknowledges;

NOW THIS DEED WITNESSES AND IT IS HEREBY AGREED AND DECLARED AS FOLLOWS:

1. The Vendor hereby grants, conveys and transfers by way of absolute sale
unto the Purchaser, all that the Schedule Property together with all rights,
easements and appurtenances thereto, to hold the same absolutely and forever.

2. The Vendor declares that the Schedule Property is free from all
encumbrances, and that no prior agreement to sell, mortgage, lease or gift
exists in respect thereof.

3. The physical possession of the Schedule Property is delivered to the
Purchaser today, and the Purchaser shall pay the taxes from the year 2013-14
onwards.

4. The Vendor shall at all times hereafter stand by and confirm this transfer
whenever required, at the cost of the Purchaser.

""" + SCHEDULE_BLOCK + """
IN WITNESS WHEREOF the Vendor and the Purchaser have hereunto set their hands
on the day and year first above written.

VENDOR: Mahadev Ningappa Kulkarni
PURCHASER: Gangadhar Mahadev Kulkarni

WITNESSES:
1. Rudragouda Yarakannavar, Honaga Village
2. K.S. Patil, Notary, Belagavi

Stamp duty of Rs. 1,29,500/- and registration fee of Rs. 18,500/- paid.
Registered in Book No. 1, Document No. BLG-3-876/2013 on 05-11-2013 before the
Joint Sub-Registrar, Belagavi."""

DEED_2024 = """SALE DEED
(Deed of Absolute Conveyance)

EXECUTED ON: 22-01-2024
REGISTERED IN: Office of the Joint Sub-Registrar, Belagavi
BOOK NO. 1, DOCUMENT NO. BLG-1-045/2024

BETWEEN

SRI GANGADHAR MAHADEV KULKARNI, aged about 54 years, S/o Mahadev Ningappa
Kulkarni, Resident of Fort Road, Belagavi,
(hereinafter referred to as "THE VENDOR")

AND

SRI RAVI GANGADHAR KULKARNI, aged about 31 years, S/o Gangadhar Mahadev
Kulkarni, Resident of Malmaruti Extension, Belagavi,
(hereinafter referred to as "THE PURCHASER")

WHEREAS the Vendor is the absolute owner of, and stands possessed of, the
Schedule Property, having acquired the same under Sale Deed dated 05-11-2013,
registered in Book No. 1 as Document No. BLG-3-876/2013 of the Office of the
Joint Sub-Registrar, Belagavi, from one Mahadev Ningappa Kulkarni;

AND WHEREAS the Vendor has enjoyed the Schedule Property openly, continuously
and undisturbedly since such acquisition, without any encumbrance whatsoever,
and all taxes have been paid up to date;

AND WHEREAS the Vendor has offered to sell the Schedule Property to the
Purchaser for a total sale consideration of Rs. 45,00,000/- (Rupees Forty Five
Lakhs only), and the Purchaser has agreed to purchase the same;

AND WHEREAS the entire sale consideration of Rs. 45,00,000/- has been paid by
the Purchaser to the Vendor by account-payee cheque No. 882041 dated 20-01-2024
drawn on HDFC Bank, Belagavi Branch, the receipt whereof the Vendor hereby
acknowledges;

NOW THIS DEED WITNESSES AND IT IS HEREBY AGREED AND DECLARED AS FOLLOWS:

1. The Vendor hereby grants, conveys and transfers by way of absolute sale
unto the Purchaser, all that the Schedule Property together with all rights,
easements and appurtenances thereto, to hold the same absolutely and forever.

2. The Vendor declares that the Schedule Property is free from all
encumbrances, and that he has not entered into any agreement to sell,
mortgage, lease or gift in respect thereof with any other person.

3. The physical possession of the Schedule Property is delivered to the
Purchaser today, and the Purchaser shall pay the taxes from the year 2024-25
onwards.

4. The Purchaser shall get his name mutated in the records of the concerned
Gram Panchayat / Taluk office in respect of the Schedule Property.

5. The Vendor shall at all times hereafter stand by and confirm this transfer
whenever required, at the cost of the Purchaser.

""" + SCHEDULE_BLOCK + """
IN WITNESS WHEREOF the Vendor and the Purchaser have hereunto set their hands
on the day and year first above written.

VENDOR: Gangadhar Mahadev Kulkarni
PURCHASER: Ravi Gangadhar Kulkarni

WITNESSES:
1. Sidagouda Patil, Honaga Village
2. R.B. Kulkarni, Advocate, Belagavi

Stamp duty of Rs. 3,15,000/- and registration fee of Rs. 45,000/- paid.
Registered in Book No. 1, Document No. BLG-1-045/2024 on 22-01-2024 before the
Joint Sub-Registrar, Belagavi."""

EC_TEXT = """KARNATAKA — FORM No. 15 (Register of transactions)
ENCUMBRANCE CERTIFICATE — ELECTRONICALLY GENERATED

Certificate No. ECD-BLG-2025-77124
Issued on: 10-10-2025 by the Joint Sub-Registrar's Office, Belagavi (e-Registration)

SEARCH PERIOD: from 01-01-1994 to 31-12-2025 (32 years)

PROPERTY SEARCHED:
Village: Honaga, Hobli: Belagavi, District: Belagavi, Karnataka
Survey No. 45/2B (Old Survey No. 45/2, Block 'B')
Total extent: 6070 square metres (1 Acre 20 Guntas)
Boundaries: North: Land of Sidagouda Patil; South: Honaga-Degulhalli Road;
East: Land of Rudragouda Yarakannavar; West: Land of Shivayogi Mudenur

TRANSACTIONS RECORDED DURING THE SEARCH PERIOD

Entry 1:
Date of registration: 08-03-1996
Registration reference: Book No. 1, Document No. BLG-1-341/1995-96, SRO Belagavi
Nature of transaction: Sale (Allotment-cum-Sale Deed under the Karnataka Urban
Development Authorities Act, 1987)
Consideration: Rs. 85,000/-
Vendors: Karnataka Urban Development Authority, Belagavi
Purchasers: Ningappa Chanaveer Kulkarni
Share conveyed: Full (6070 sq m)
Minor or legal-heir party: No. Agreement to sell: No.

Entry 2:
Date of registration: 15-07-2004
Registration reference: Book No. 1, Document No. BLG-2-511/2004, Joint SRO Belagavi
Nature of transaction: Sale
Consideration: Rs. 6,50,000/-
Vendors: Ningappa Chanaveer Kulkarni
Purchasers: Mahadev Ningappa Kulkarni
Share conveyed: Full (6070 sq m)
Minor or legal-heir party: No. Agreement to sell: No.

Entry 3:
Date of registration: 05-11-2013
Registration reference: Book No. 1, Document No. BLG-3-876/2013, Joint SRO Belagavi
Nature of transaction: Sale
Consideration: Rs. 18,50,000/-
Vendors: Mahadev Ningappa Kulkarni
Purchasers: Gangadhar Mahadev Kulkarni
Share conveyed: Full (6070 sq m)
Minor or legal-heir party: No. Agreement to sell: No.

Entry 4:
Date of registration: 22-01-2024
Registration reference: Book No. 1, Document No. BLG-1-045/2024, Joint SRO Belagavi
Nature of transaction: Sale
Consideration: Rs. 45,00,000/-
Vendors: Gangadhar Mahadev Kulkarni
Purchasers: Ravi Gangadhar Kulkarni
Share conveyed: Full (6070 sq m)
Minor or legal-heir party: No. Agreement to sell: No.

NIL PERIODS:
For the period 01-01-1994 to 07-03-1996 and for the period 23-01-2024 to
31-12-2025, no encumbrance, transaction or lis pendens is recorded in respect
of Survey No. 45/2B of Honaga Village.

This certificate is computer-generated and digitally signed.
Digitally signed by: Assistant Sub-Registrar (e-Registration), Belagavi
Date of signature: 10-10-2025"""

RTC_TEXT = """KARNATAKA GOVERNMENT — FORM No. 2 / PAHANI (RTC)
RECORD OF RIGHTS, TENANCY AND CROPS — VILLAGE: HONAGA
HOBLI: BELAGAVI, DISTRICT: BELAGAVI

Year of Pahani: 2024-25 (issued 05-09-2025)

Survey No.: 45/2B (Old Survey No. 45/2, Block 'B')
Hissa/Block: 'B'
Total extent: 6070 square metres (1 Acre 20 Guntas)
Land classification: Converted residential
(Conversion Order No. ALN/CR/45/1994-95 dated 19-12-1994, Deputy Commissioner, Belagavi)

OWNER / POSSESSOR:
Ravi Gangadhar Kulkarni, aged about 31 years, S/o Gangadhar Mahadev Kulkarni,
Resident of Malmaruti Extension, Belagavi

Khata No.: 1221/HON
Assessment (site): Rs. 120/- per annum, paid up to date to Gram Panchayat, Honaga

MUTATION REGISTER:
Mutation Entry No. 12/2024-25 dated 18-02-2024:
"Mutation effected on the basis of Sale Deed Book No. 1, Document No.
BLG-1-045/2024 dated 22-01-2024. Name of Gangadhar Mahadev Kulkarni deleted and
name of Ravi Gangadhar Kulkarni entered in respect of Survey No. 45/2B to the
extent of 6070 sq m. Mutation certified and confirmed."

Crops: Nil (residential site)
Tenanted: Nil
Land acquisition proceedings: Nil
Court cases / litigation on this survey number: Nil

Signed: Revenue Inspector, Honaga Circle, Belagavi Taluk
Countersigned: Tahsildar, Belagavi"""

DOCUMENTS = (
    ("DOC-SD-1996", 0, "KUDA_AllotmentSaleDeed_1996-03-08.pdf", "SALE_DEED", DEED_1996,
     "KUDA allotment-cum-sale deed 08-03-1996 (Doc BLG-1-341/1995-96): Karnataka Urban "
     "Development Authority conveys Survey No. 45/2B, Honaga Village (6070 sq m, 1A 20G) "
     "to Ningappa Chanaveer Kulkarni for Rs 85,000. Chain root."),
    ("DOC-SD-2004", 1, "SaleDeed_2004-07-15_Kulkarni.pdf", "SALE_DEED", DEED_2004,
     "Sale deed 15-07-2004 (Doc BLG-2-511/2004): Ningappa Chanaveer Kulkarni sells Survey "
     "No. 45/2B, Honaga (1A 20G) to Mahadev Ningappa Kulkarni for Rs 6,50,000; recites the "
     "1996 KUDA deed as his title."),
    ("DOC-SD-2013", 2, "SaleDeed_2013-11-05_Kulkarni.pdf", "SALE_DEED", DEED_2013,
     "Sale deed 05-11-2013 (Doc BLG-3-876/2013): Mahadev Ningappa Kulkarni sells Survey "
     "No. 45/2B to Gangadhar Mahadev Kulkarni for Rs 18,50,000; recites the 2004 deed."),
    ("DOC-SD-2024", 3, "SaleDeed_2024-01-22_Kulkarni.pdf", "SALE_DEED", DEED_2024,
     "Sale deed 22-01-2024 (Doc BLG-1-045/2024): Gangadhar Mahadev Kulkarni sells Survey "
     "No. 45/2B to Ravi Gangadhar Kulkarni for Rs 45,00,000; recites the 2013 deed. "
     "Current-owner transaction."),
    ("DOC-EC-2025", 4, "EncumbranceCertificate_1994-2025.pdf", "ENCUMBRANCE_CERTIFICATE", EC_TEXT,
     "Encumbrance certificate, search 01-01-1994 to 31-12-2025: exactly four entries — the "
     "1996 KUDA conveyance and the 2004, 2013 and 2024 sales; no encumbrance before or after."),
    ("DOC-RTC-2025", 5, "RTC_Pahani_2024-25_Honaga.pdf", "RTC_PAHANI", RTC_TEXT,
     "RTC Pahani 2024-25 for Survey No. 45/2B: owner Ravi Gangadhar Kulkarni; mutation "
     "No. 12/2024-25 (18-02-2024) from the 2024 sale deed; converted residential, khata "
     "1221/HON; no litigation."),
)


def _cleanup() -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        for table in ("documents", "title_chains", "case_results", "case_memory",
                      "evidence_requirements"):
            try:
                cursor.execute(f"DELETE FROM {table} WHERE case_id = %s", (CASE_ID,))
            except Exception as exc:  # table not migrated yet on this DB — skip it
                print(f"  (skip {table}: {exc.__class__.__name__})")
                conn.rollback()
        try:
            cursor.execute("DELETE FROM cases WHERE id = %s", (CASE_ID,))
        except Exception as exc:
            print(f"  (skip cases: {exc.__class__.__name__})")
            conn.rollback()
        conn.commit()


def main() -> None:
    _cleanup()
    init_case(case_id=CASE_ID, total_docs=len(DOCUMENTS), user_id=None)
    for doc_id, idx, filename, doc_type, text, summary in DOCUMENTS:
        init_document(case_id=CASE_ID, doc_id=doc_id, doc_index=idx,
                      filename=filename, expected_type=doc_type)
        update_document_status(
            case_id=CASE_ID, doc_id=doc_id, status="structured",
            document_type=doc_type, merged_ocr_text=text, summary=summary,
            page_count=4 if "SALE_DEED" in doc_type else 2,
        )
    update_case_status(case_id=CASE_ID)
    print(f"Seeded {CASE_ID}: {len(DOCUMENTS)} structured documents, clean 4-link chain.")


if __name__ == "__main__":
    main()
