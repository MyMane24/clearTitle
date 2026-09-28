import unittest

from backend.shared.ec_ledger import merge_split_ledger


class MergeSplitLedgerTest(unittest.TestCase):
    def test_continuation_merged_into_predecessor(self):
        ledger = [
            {
                "parties": {"vendors": ["Sri.NARAYAN RAMU AVACHARI"], "purchasers": []},
                "execution_date": "2025-03-05",
                "transaction_type": "Deposit of",
                "transaction_index": 1,
                "registration_reference": "BES-1-08094-2024-25",
                "property_details": {"boundaries": {"north": "CTS NO 1360 B/2"}},
            },
            {
                "parties": {"vendors": ["Sri.POOJA W/o. NARAYAN AVACHARI"], "purchasers": []},
                "execution_date": None,
                "transaction_type": "Title Deed",
                "transaction_index": 2,
                "registration_reference": None,
                "financials": {"consideration_amount": 3880000},
                "property_details": {
                    "boundaries": {"south": "ROAD"},
                    "plot_no": "9",
                    "pid_no": "116057",
                },
            },
            {
                "parties": {
                    "vendors": ["Sri.KIRAN YALLURKAR"],
                    "purchasers": ["Sri.NARAYAN AVACHARI"],
                },
                "execution_date": "2024-10-04",
                "transaction_type": "Sale",
                "transaction_index": 3,
                "registration_reference": "BEL-1-08825-2024-25",
            },
        ]
        merged = merge_split_ledger(ledger)
        self.assertEqual(len(merged), 2)
        first = merged[0]
        self.assertEqual(first["transaction_index"], 1)
        self.assertEqual(first["registration_reference"], "BES-1-08094-2024-25")
        self.assertEqual(first["execution_date"], "2025-03-05")
        self.assertEqual(first["transaction_type"], "Deposit of")
        self.assertEqual(
            first["parties"]["vendors"],
            ["Sri.NARAYAN RAMU AVACHARI", "Sri.POOJA W/o. NARAYAN AVACHARI"],
        )
        self.assertEqual(first["financials"]["consideration_amount"], 3880000)
        self.assertEqual(first["property_details"]["plot_no"], "9")
        self.assertEqual(first["property_details"]["boundaries"]["north"], "CTS NO 1360 B/2")
        self.assertEqual(first["property_details"]["boundaries"]["south"], "ROAD")
        self.assertEqual(merged[1]["transaction_index"], 2)
        self.assertEqual(merged[1]["execution_date"], "2024-10-04")

    def test_genuine_records_untouched(self):
        ledger = [
            {
                "execution_date": "2025-03-05",
                "registration_reference": "BES-1-08094-2024-25",
                "transaction_index": 1,
            },
            {
                "execution_date": "2024-10-04",
                "registration_reference": "BEL-1-08825-2024-25",
                "transaction_index": 2,
            },
        ]
        merged = merge_split_ledger(ledger)
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
