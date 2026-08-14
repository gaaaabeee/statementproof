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

from statementproof import formats  # noqa: E402

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

BOA_TEXT = """
Customer service information
Customer service: 1.800.432.1000
En Español: 1.800.688.6086
bankofamerica.com
Bank of America, N.A. P.O. Box 25118 Tampa, FL 33622-5118
Your Adv Plus Banking
for June 16, 2026 to July 17, 2026 Account number: 0000 0000 0000
Account summary
Beginning balance on June 16, 2026 $1,000.00
Ending balance on July 17, 2026 $1,500.00
"""

WELLSFARGO_TEXT = """
Account Statement
Statement Date: May 3, 2002
SAMPLE
Questions about this statement or your accounts? Call: 800-869-3557
(1-800-TO-WELLS). Or write: WELLS FARGO BANK, N.A., P.O. BOX 6995, PORTLAND,
OR 97228-6995.
Advantage Checking
Account Number: 111-2222222
Activity summary
Balance on 04/03 $4,721.33
Activity detail
Daily balance summary
"""

OTHER_BANK_TEXT = """
Citibank Basic Checking
Statement period January 1, 2025 - January 31, 2025
Beginning balance $500.00
"""


class TestScoring(unittest.TestCase):
    def fmt(self, name):
        return formats.BY_NAME[name]

    def test_each_format_recognises_its_own_text(self):
        self.assertGreater(self.fmt("chase_checking").score(CHECKING_TEXT), 0)
        self.assertGreater(self.fmt("chase_credit").score(CREDIT_TEXT), 0)
        self.assertGreater(self.fmt("boa_checking").score(BOA_TEXT), 0)
        self.assertGreater(self.fmt("wellsfargo_checking").score(WELLSFARGO_TEXT), 0)

    def test_formats_reject_each_other(self):
        # The failure that matters: one bank's parser run over another's
        # statement would emit plausible, wrong numbers. Two checking formats
        # from different banks is the case most likely to collide.
        texts = {"chase_checking": CHECKING_TEXT, "chase_credit": CREDIT_TEXT,
                 "boa_checking": BOA_TEXT, "wellsfargo_checking": WELLSFARGO_TEXT}
        for name, text in texts.items():
            for other, _ in texts.items():
                if other == name:
                    continue
                self.assertEqual(self.fmt(other).score(text), 0,
                                 f"{other} should not claim {name}'s statement")

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

    def test_format_names_are_unique(self):
        names = [f.name for f in formats.FORMATS]
        self.assertEqual(len(names), len(set(names)))

    def test_several_banks_may_share_an_account_kind(self):
        # Two banks both offering checking is normal. What must not happen is a
        # lookup keyed by account kind quietly resolving to one of them.
        kinds = [f.account_kind for f in formats.FORMATS]
        self.assertGreater(len(kinds), len(set(kinds)),
                           "expected at least two formats sharing an account kind")

    def test_polarity_is_consistent_per_account_kind(self):
        # A wrong polarity flips the sign of an entire account in the
        # net-position check while every per-statement check still passes.
        for fmt in formats.FORMATS:
            self.assertEqual(formats.ACCOUNT_POLARITY[fmt.account_kind], fmt.polarity,
                             fmt.name)
        self.assertEqual(formats.ACCOUNT_POLARITY["checking"], formats.ASSET)
        self.assertEqual(formats.ACCOUNT_POLARITY["credit"], formats.LIABILITY)

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
