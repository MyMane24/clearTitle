import unittest

from backend.services.report import _build_subject, _owner_blocks, _parties_effect


class ReportPartiesTest(unittest.TestCase):
    """The extractor emits parties as plain strings; dict entries still supported."""

    def test_parties_effect_accepts_strings(self):
        tx = {
            "parties": {
                "vendors": ["M/s Sapthagiri Associates", "Ravindra Shivaputra Chobari"],
                "purchasers": ["Chandrashekhar S. Hadimani"],
            }
        }
        self.assertEqual(
            _parties_effect(tx),
            "M/s Sapthagiri Associates → Ravindra Shivaputra Chobari → Chandrashekhar S. Hadimani",
        )

    def test_parties_effect_accepts_dicts_and_dedupes(self):
        tx = {
            "parties": {
                "vendors": [
                    {"entity_name": "K.U.D.C. Belagavi"},
                    {"entity_name": "Basavaraj Hiremath"},
                ],
                "purchasers": [{"entity_name": "Basavaraj Hiremath"}],
            }
        }
        self.assertEqual(_parties_effect(tx), "K.U.D.C. Belagavi → Basavaraj Hiremath")

    def test_parties_effect_empty_purchasers(self):
        tx = {"parties": {"vendors": ["Sri.Prerana Shirodkar"], "purchasers": []}}
        self.assertEqual(_parties_effect(tx), "Sri.Prerana Shirodkar")

    def test_owner_blocks_from_strings(self):
        sd = {
            "parties": {
                "purchasers": ["Smt.Prerana Praveen Shirodkar", "Sri.Praveen Bhausaheb Shirodkar"]
            }
        }
        blocks = _owner_blocks(sd)
        self.assertEqual([b["label"] for b in blocks], ["Current Owner", "Co-Owner 2"])
        self.assertEqual(blocks[0]["name"], "Smt.Prerana Praveen Shirodkar")
        self.assertEqual(blocks[1]["address"], "")

    def test_owner_blocks_from_dicts(self):
        sd = {
            "parties": {
                "purchasers": [
                    {
                        "entity_name": "Anusuya",
                        "represented_by": "Basavaraj Hiremath",
                        "address": "Belagavi",
                    }
                ]
            }
        }
        block = _owner_blocks(sd)[0]
        self.assertEqual(block["name"], "Anusuya (Rep. by Basavaraj Hiremath)")
        self.assertEqual(block["address"], "Belagavi")

    def test_build_subject_from_strings(self):
        sd = {
            "property_schedule": {"survey_number": "699A/15"},
            "parties": {"purchasers": ["Basavaraj Hiremath"]},
        }
        self.assertEqual(
            _build_subject(sd), "Legal opinion in respect of 699A/15 held by Basavaraj Hiremath."
        )


if __name__ == "__main__":
    unittest.main()
