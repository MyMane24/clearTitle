import re
import unittest

from backend.prompts.loader import load_prompt
from backend.services.agent_schemas import TransactionVerification
from backend.services.agent_tools import _MAX_REPORT_CHARS, _result_compactness_errors


class TestVerificationReportContract(unittest.TestCase):
    def setUp(self):
        self.task = load_prompt("agent_verify_task")

    def test_prompt_fixes_only_the_essentials(self):
        flat = " ".join(self.task.split())
        for fragment in (
            "**Verdict:**",
            "one bracket per document",
            "## Earlier transactions",
            "never a digest of the instrument",
        ):
            self.assertIn(fragment, flat)

    def test_prompt_leaves_the_layout_to_the_content(self):
        self.assertIn("let the content decide the layout", self.task)
        for capability in ("tables", "numbered lists", "blockquote", "bullet lists"):
            self.assertIn(capability, self.task)
        # No mandated section names: headings are named for what they say.
        for fixed in ("## Confirmed", "## Issues and discrepancies", "## Unresolved or missing"):
            self.assertNotIn(fixed, self.task)

    def test_examples_follow_the_citation_rule(self):
        examples = self.task.split("Illustrative shapes only")[1].split("CHAIN CONTINUITY")[0]
        for bracket in re.findall(r"\[([^\]]+)\]", examples):
            self.assertEqual(len(re.findall(r"DOC_\d+", bracket)), 1, bracket)

    def test_tool_schema_describes_the_flexible_report(self):
        description = TransactionVerification.model_json_schema()["properties"]["report"]["description"]
        self.assertIn("whatever structure fits the findings", description)
        self.assertIn("never a retelling of the deed", description)

    def test_overlong_report_is_rejected_with_a_rewrite_instruction(self):
        errors = _result_compactness_errors({"report": "x " * _MAX_REPORT_CHARS, "required_documents": []})
        self.assertTrue(any("short verification report" in error for error in errors))
        self.assertEqual(_result_compactness_errors({"report": "**Verdict:** ok.", "required_documents": []}), [])


if __name__ == "__main__":
    unittest.main()
