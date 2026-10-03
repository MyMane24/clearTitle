import unittest

from backend.services.verify import _measurement_items
from backend.shared.measurements import (
    boundaries_similar,
    compare_areas,
    dims_to_sqm,
    parse_area,
    parse_dimensions,
)

AREA_TOL = 1e-2  # sq m


class TestMeasurements(unittest.TestCase):
    def assert_area(self, value, expected):
        got = parse_area(value)
        self.assertIsNotNone(got, value)
        self.assertAlmostEqual(got, expected, delta=AREA_TOL)

    def test_parse_area_bare_is_sqm(self):
        self.assert_area("111.48", 111.48)
        self.assert_area("69.67725", 69.67725)

    def test_parse_area_units(self):
        self.assert_area("1200 sq ft", 111.4837)      # 1200 ft2 = 111.48 m2 (user's deed)
        self.assert_area("641.9 sq m", 641.9)
        self.assert_area("2 acre", 8093.71)
        self.assert_area("30 cents", 1214.06)
        self.assert_area("1 gunta", 101.1714)

    def test_parse_area_unparseable(self):
        self.assertIsNone(parse_area(None))
        self.assertIsNone(parse_area(""))
        self.assertIsNone(parse_area("east road"))

    def test_parse_dimensions(self):
        self.assertEqual(parse_dimensions("9.14 X 12.19"), [9.14, 12.19])
        self.assertEqual(parse_dimensions("9.14x12.19"), [9.14, 12.19])
        self.assertAlmostEqual(parse_dimensions("30 ft X 40 ft")[0], 9.144, delta=0.01)
        self.assertIsNone(parse_dimensions("north 50 ft"))

    def test_dims_to_sqm(self):
        self.assertAlmostEqual(dims_to_sqm("9.14 X 12.19"), 111.4166, delta=0.01)

    def test_compare_areas(self):
        # the user's real case: dims product == declared == 1200 sq ft
        self.assertEqual(compare_areas("9.14 X 12.19", "111.48 sq m"), "VERIFIED")
        self.assertEqual(compare_areas("1200 sq ft", "111.48"), "VERIFIED")
        self.assertEqual(compare_areas("1 gunta", "101.17"), "VERIFIED")
        # genuinely different area -> flagged, not silently accepted
        self.assertEqual(compare_areas("9.14 X 12.19", "69.67725"), "FLAG")
        self.assertEqual(compare_areas("111.48", ""), "N/A")

    def test_boundaries_similar(self):
        b = {"north": "CTS NO 1360 B/2", "east": "ROAD", "west": "DREDGE", "south": "ROAD"}
        self.assertEqual(boundaries_similar(b, dict(b)), "VERIFIED")
        self.assertEqual(boundaries_similar(b, {"north": "HOUSE OF X"}), "NEEDS_REVIEW")
        self.assertEqual(boundaries_similar(b, {}), "N/A")
        self.assertEqual(boundaries_similar({}, {}), "N/A")


class TestVerifyMeasurementItems(unittest.TestCase):
    def test_user_deed_example(self):
        sd = {"property_schedule": {"measurements": {
            "dimensions_text": "9.14 X 12.19",
            "total_land_area_sqmtr": "111.48",
            "super_built_up_area_sqft": "1200 sq ft",
        }, "boundaries": {"north": "CTS 1360B/9"}}}
        ec = {"historical_ledger": [{"property_details": {
            "measurements": {"measurements_text": "1200 sq ft"},
            "boundaries": {"north": "CTS 1360B/9", "east": "ROAD"},
        }}]}
        khata = {"property_details": {
            "area_sq_meters": "111.48", "boundaries": {"north": "CTS 1360B/9"},
        }}
        items = _measurement_items(sd, ec, khata)
        by_field = {it["field"]: it["status"] for it in items}
        self.assertEqual(by_field["Land area (dimensions vs declared)"], "VERIFIED")
        self.assertEqual(by_field["Land area (SD vs EC)"], "VERIFIED")
        self.assertEqual(by_field["Land area (SD vs Khata)"], "VERIFIED")
        self.assertEqual(by_field["Boundaries (SD vs EC)"], "VERIFIED")
        self.assertEqual(by_field["Boundaries (SD vs Khata)"], "VERIFIED")

    def test_empty_docs_produce_no_items(self):
        self.assertEqual(_measurement_items({}, {"historical_ledger": []}, None), [])


if __name__ == "__main__":
    unittest.main()
