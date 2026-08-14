"""Tests for ACH descriptor handling.

    ./.venv/bin/python -m unittest discover -s tests

An ACH descriptor is a network-standard record rather than a bank's formatting
choice, so this handling is shared across formats. All values below are
invented.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statementproof import config, merchants  # noqa: E402

# Two months of the same payee: the transaction reference changes, the
# originator id does not.
BOA_ACH_A = "Example Properties DES:WEB PMTS ID:AB12CD INDN:A Person CO ID:9876543210"
BOA_ACH_B = "Example Properties DES:WEB PMTS ID:EF34GH INDN:A Person CO ID:9876543210"
CHASE_ACH = "Example Employer Payroll PPD ID: 1122334455"
CHASE_WEB = "Somebank Ck Webxfr P2P A Person Web ID: 5566778899"


class TestOriginator(unittest.TestCase):
    def test_extracts_co_id(self):
        self.assertEqual(merchants.ach_originator(BOA_ACH_A), "9876543210")

    def test_extracts_typed_id(self):
        self.assertEqual(merchants.ach_originator(CHASE_ACH), "1122334455")
        self.assertEqual(merchants.ach_originator(CHASE_WEB), "5566778899")

    def test_is_stable_while_the_reference_changes(self):
        # This is the whole point: keying on the text makes one payee look like
        # a new merchant every month.
        self.assertEqual(merchants.ach_originator(BOA_ACH_A),
                         merchants.ach_originator(BOA_ACH_B))

    def test_absent_on_a_plain_card_descriptor(self):
        self.assertIsNone(merchants.ach_originator("SOME MERCHANT HOUSTON TX"))


class TestTailStripping(unittest.TestCase):
    def test_variants_collapse_to_one_payee(self):
        self.assertEqual(merchants.strip_ach_tail(BOA_ACH_A), "Example Properties")
        self.assertEqual(merchants.strip_ach_tail(BOA_ACH_A),
                         merchants.strip_ach_tail(BOA_ACH_B))

    def test_account_holder_name_is_dropped(self):
        # INDN: is the account holder, who has no business in a merchant label.
        self.assertNotIn("A Person", merchants.strip_ach_tail(BOA_ACH_A))

    def test_chase_payee_survives(self):
        self.assertEqual(merchants.strip_ach_tail(CHASE_ACH), "Example Employer Payroll")

    def test_non_ach_text_is_unchanged(self):
        for text in ("SOME MERCHANT HOUSTON TX", "DD *DOORDASH 8559731040 CA"):
            self.assertEqual(merchants.strip_ach_tail(text), text)


class TestNormalizeCollapsesVariants(unittest.TestCase):
    def test_one_payee_yields_one_merchant(self):
        a = merchants.normalize(BOA_ACH_A, "checking", "withdrawal")
        b = merchants.normalize(BOA_ACH_B, "checking", "withdrawal")
        self.assertEqual(a, b)
        self.assertEqual(a[0], "Example Properties")

    def test_unknown_payee_is_uncategorized_not_guessed(self):
        self.assertEqual(
            merchants.normalize(BOA_ACH_A, "checking", "withdrawal")[1], "uncategorized")


class TestAchRules(unittest.TestCase):
    """A rule keyed on the originator id, from the user's config."""

    def rules(self, payload):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            return fh.name

    def test_ach_table_is_read_and_normalized(self):
        # Keys are whitespace- and case-normalized, so a hand-edited config
        # with a stray space still matches.
        path = self.rules({"ach": {" 9876543210 ": {"merchant": "Rent",
                                                    "category": "Housing"}}})
        os.environ["STATEMENT_RULES"] = path
        try:
            loaded = config.load()
            table = config.ach_rules(loaded)
            self.assertEqual(table["9876543210"], ("Rent", "Housing"))
        finally:
            os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")
            os.unlink(path)

    def test_incomplete_entries_are_ignored(self):
        table = config.ach_rules({"ach": {
            "1": {"merchant": "No category"},
            "2": {"category": "No merchant"},
            "3": "not a dict",
            "4": {"merchant": "Fine", "category": "Housing"},
        }})
        self.assertEqual(list(table), ["4"])

    def test_missing_ach_section_is_not_an_error(self):
        self.assertEqual(config.ach_rules({}), {})


if __name__ == "__main__":
    unittest.main()
