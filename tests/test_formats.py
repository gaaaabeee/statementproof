"""Tests for statement format detection.

    ./.venv/bin/python -m unittest discover -s tests

Detection is scored against text, so these run on representative text snippets
rather than real PDFs -- which means the project can test its routing without
committing anybody's bank statements to source control.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statement_reconciler import formats  # noqa: E402

CHECKING_TEXT = """
JPMorgan Chase Bank, N.A.
CUSTOMER SERVICE INFORMATION
Service Center: 1-800-000-0000
January 08, 2025 through February 06, 2025
Account Number: 000000000000000
CHECKING SUMMARY Chase Total Checking
Beginning Balance $1,000.00
TRANSACTION DETAIL
DATE DESCRIPTION AMOUNT BALANCE
"""

CREDIT_TEXT = """
ACCOUNT SUMMARY
Manage your account online at: www.chase.com/cardhelp
Minimum Payment Due: $40.00
Account Number: XXXX XXXX XXXX 0000
Previous Balance $2,000.00
Opening/Closing Date 01/03/25 - 02/02/25
Credit Access Line $9,999
"""

OTHER_BANK_TEXT = """
Wells Fargo Everyday Checking
Statement period January 1, 2025 - January 31, 2025
Beginning balance $500.00
"""


class TestScoring(unittest.TestCase):
    def fmt(self, name):
        return formats.BY_NAME[name]

    def test_each_format_recognises_its_own_text(self):
        self.assertGreater(self.fmt("chase_checking").score(CHECKING_TEXT), 0)
        self.assertGreater(self.fmt("chase_credit").score(CREDIT_TEXT), 0)

    def test_formats_reject_each_other(self):
        # The failure that matters: a card parser run over a checking statement
        # would emit plausible, wrong numbers.
        self.assertEqual(self.fmt("chase_credit").score(CHECKING_TEXT), 0)
        self.assertEqual(self.fmt("chase_checking").score(CREDIT_TEXT), 0)

    def test_unknown_bank_matches_nothing(self):
        for fmt in formats.FORMATS:
            self.assertEqual(fmt.score(OTHER_BANK_TEXT), 0, fmt.name)

    def test_score_rises_with_corroborating_markers(self):
        minimal = "CHECKING SUMMARY"
        self.assertLess(
            self.fmt("chase_checking").score(minimal),
            self.fmt("chase_checking").score(CHECKING_TEXT),
        )


class TestRegistry(unittest.TestCase):
    def test_polarity_is_declared_for_every_format(self):
        # The whole-corpus reconciliation weights each account by this, so a
        # missing or wrong polarity would silently break the net-position check.
        for fmt in formats.FORMATS:
            self.assertIn(fmt.polarity, (formats.ASSET, formats.LIABILITY), fmt.name)

    def test_account_kinds_are_unique(self):
        kinds = [f.account_kind for f in formats.FORMATS]
        self.assertEqual(len(kinds), len(set(kinds)))

    def test_every_format_is_callable_and_named(self):
        for fmt in formats.FORMATS:
            self.assertTrue(fmt.name and fmt.label)
            self.assertTrue(callable(fmt.parse))
            self.assertTrue(fmt.required, "a format with no required marker matches everything")


class TestDetectionErrors(unittest.TestCase):
    def test_missing_file_is_reported_not_raised(self):
        d = formats.detect(os.path.join(HERE, "does-not-exist.pdf"))
        self.assertFalse(d.ok)
        self.assertIn("does-not-exist.pdf", d.describe())

    def test_non_pdf_is_reported_not_raised(self):
        d = formats.detect(os.path.join(HERE, "test_formats.py"))
        self.assertFalse(d.ok)
        self.assertTrue(d.error)

    def test_unmatched_describe_lists_supported_formats(self):
        d = formats.Detection(path="/tmp/mystery.pdf")
        text = d.describe()
        self.assertIn("no supported format matched", text)
        for fmt in formats.FORMATS:
            self.assertIn(fmt.label, text)


if __name__ == "__main__":
    unittest.main()
