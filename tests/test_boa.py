"""Tests for the Bank of America checking parser.

    ./.venv/bin/python -m unittest discover -s tests

These exercise the line-level logic against representative *text*, so the
project never needs a real statement in source control. Values are invented.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statementproof import boa  # noqa: E402


class TestMoney(unittest.TestCase):
    def test_signs_and_separators(self):
        self.assertEqual(boa.money("2,364.83"), 2364.83)
        self.assertEqual(boa.money("-3,474.03"), -3474.03)
        self.assertEqual(boa.money("$12,059.93"), 12059.93)
        self.assertEqual(boa.money("-$1,914.40"), -1914.40)
        self.assertEqual(boa.money("-0.00"), 0.0)


class TestRowMatching(unittest.TestCase):
    def row(self, line):
        m = boa.ROW.match(line)
        return None if not m else (m.group(4), boa.money(m.group(5)))

    def test_deposit_row(self):
        desc, amt = self.row(
            "06/18/26 7509 EXAMPLE CO DES:PAYROLL ID:410 INDN:A PERSON CO ID:1 PPD 2,364.83")
        self.assertEqual(amt, 2364.83)
        self.assertTrue(desc.startswith("7509 EXAMPLE CO"))

    def test_subtraction_row_keeps_its_sign(self):
        # BoA prints the sign; it is read rather than inferred from the section,
        # so a misfiled row cannot silently flip direction.
        self.assertEqual(self.row("06/16/26 PURCHASE 0615 SOME MERCHANT CA -37.37")[1], -37.37)

    def test_long_trailing_reference_is_part_of_the_description(self):
        desc, amt = self.row(
            "06/16/26 CHECKCARD 0614 A MERCHANT HOUSTON TX 75369436166913405028561 -48.19")
        self.assertEqual(amt, -48.19)
        self.assertIn("75369436166913405028561", desc)

    def test_a_total_line_is_not_a_row(self):
        self.assertIsNone(self.row("Total ATM and debit card subtractions -$3,474.03"))


class TestStructuralPatterns(unittest.TestCase):
    def test_summary_row_is_distinguished_from_section_header(self):
        # "Other subtractions" is both a summary line (with an amount) and a
        # section header (without one). Confusing them loses a whole section.
        self.assertTrue(boa.SUMMARY_ROW.match("Other subtractions -1,914.40"))
        self.assertIsNone(boa.SUMMARY_ROW.match("Other subtractions"))
        self.assertTrue(boa.SECTION_HEADER.match("Other subtractions"))

    def test_continued_headers_resume_a_section(self):
        self.assertTrue(boa.SECTION_HEADER.match("ATM and debit card subtractions - continued"))

    def test_section_totals_are_captured(self):
        m = boa.SECTION_TOTAL.match("Total other subtractions -$1,914.40")
        self.assertIsNotNone(m)
        self.assertEqual(boa.money(m.group(2)), -1914.40)

    def test_column_header_variants_are_noise(self):
        for line in ("Date Description Amount",
                     "Date Transaction description Amount",
                     "continued on the next page",
                     "Page 3 of 8"):
            self.assertTrue(boa.NOISE.match(line), line)

    def test_wrapped_fragment_fits_the_continuation_limit(self):
        # The longest wrap seen in real statements is an international wire's
        # originator block; marketing copy is longer and must not be absorbed.
        fragment = ("ORIG:1/A Person ID:XX00000000000000 ORIG BK:SOME BANK NAME LONG")
        self.assertLessEqual(len(fragment), boa.MAX_CONTINUATION)
        marketing = ("Bank of America champions everyone who dares to ask What would "
                     "you like the power to do? Visit an example page for details")
        self.assertGreater(len(marketing), boa.MAX_CONTINUATION)


class TestEnvelope(unittest.TestCase):
    """BoA wraps the merchant in the channel that produced the transaction."""

    def test_channel_prefix_and_auth_code_are_removed(self):
        self.assertEqual(
            boa.strip_envelope(
                "CHECKCARD 0614 SOME MERCHANT HOUSTON TX 75369436166913405028561"),
            "SOME MERCHANT HOUSTON TX")
        self.assertEqual(
            boa.strip_envelope("MOBILE PURCHASE 0625 A VENDOR TROY MI"),
            "A VENDOR TROY MI")

    def test_a_brand_survives_the_envelope(self):
        # The bug this guards: over-stripping left only "Checkcard 0402" and
        # ate the airline, which is why envelope removal belongs to the parser
        # rather than the shared cleanup.
        out = boa.strip_envelope("CHECKCARD 0402 SOMEAIRLINE 8009322732 TX 55432866093201174804045")
        self.assertIn("SOMEAIRLINE", out)

    def test_doubled_name_keeps_the_fuller_copy(self):
        self.assertEqual(
            boa.strip_envelope(
                "EXAMPLE SHOP 06/22 #000035420 MOBILE PURCHASE EXAMPLE SHOPPE HOUSTON TX"),
            "EXAMPLE SHOPPE HOUSTON TX")

    def test_doubled_name_keeps_the_brand_when_the_second_copy_is_an_address(self):
        # "BRAND 05/17 #000002369 MOBILE PURCHASE 7810 SOME FREEWAY" -- taking
        # the second copy blindly loses the brand and yields a street address.
        self.assertEqual(
            boa.strip_envelope("BRAND STORE 05/17 #000002369 MOBILE PURCHASE 7810 SOME FREEWAY HOUSTON"),
            "BRAND STORE")

    def test_plain_descriptor_is_untouched(self):
        self.assertEqual(boa.strip_envelope("Zelle payment to A Person Conf# abc123"),
                         "Zelle payment to A Person Conf# abc123")


class TestValidation(unittest.TestCase):
    def make(self, txns, summary):
        from datetime import date
        from statementproof.records import Statement, Txn
        s = Statement(account="checking", account_last4="0000", path="x.pdf",
                      close_date=date(2026, 7, 17), period_start=date(2026, 6, 16),
                      period_end=date(2026, 7, 17), summary=dict(summary))
        for amt in txns:
            s.txns.append(Txn(account="checking", account_last4="0000",
                              date=date(2026, 7, 1), description="d", amount=amt,
                              kind="deposit" if amt > 0 else "withdrawal",
                              statement_close=date(2026, 7, 17),
                              period_start=date(2026, 6, 16), period_end=date(2026, 7, 17),
                              source_file="x.pdf", source_line=1))
        boa._validate(s)
        return s

    def test_consistent_statement_passes(self):
        s = self.make([100.0, -40.0], {
            "beginning_balance": 1000.0, "ending_balance": 1060.0,
            "total_deposits": 100.0, "total_atm_debit": -40.0,
            "deposits": 100.0, "atm_debit": -40.0,
        })
        self.assertTrue(s.ok, [c.name for c in s.checks if not c.ok])

    def test_a_missing_row_is_caught(self):
        s = self.make([100.0], {          # the -40.00 row was dropped
            "beginning_balance": 1000.0, "ending_balance": 1060.0,
            "total_deposits": 100.0, "total_atm_debit": -40.0,
        })
        failed = {c.name for c in s.checks if not c.ok}
        self.assertIn("subtractions_total", failed)
        self.assertIn("ending_balance", failed)

    def test_zero_activity_statement_still_reconciles(self):
        # A month with no transactions is valid, and the balance check is the
        # only evidence the statement was read correctly.
        s = self.make([], {"beginning_balance": 160.0, "ending_balance": 160.0})
        self.assertEqual(s.txns, [])
        self.assertTrue(s.ok)
        self.assertTrue(any(c.name == "ending_balance" for c in s.checks))

    def test_summary_disagreeing_with_section_totals_is_caught(self):
        s = self.make([100.0], {
            "beginning_balance": 1000.0, "ending_balance": 1100.0,
            "total_deposits": 100.0, "deposits": 999.0,
        })
        self.assertIn("summary_agrees_deposits", {c.name for c in s.checks if not c.ok})


if __name__ == "__main__":
    unittest.main()
