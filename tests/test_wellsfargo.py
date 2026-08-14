"""Tests for the Wells Fargo checking parser (experimental).

    ./.venv/bin/python -m unittest discover -s tests

These exercise the line-level logic against representative *text* shaped like
Wells Fargo's official specimen statement (see wellsfargo.py's module
docstring for where that specimen came from and why this format is marked
experimental). Values are invented; no real account ever touches this file.
"""

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statementproof import wellsfargo as wf  # noqa: E402
from statementproof.records import Statement, Txn  # noqa: E402


class TestRowMatching(unittest.TestCase):
    def test_single_line_row(self):
        hit = wf.ROW.match("04/29 Deposit $31.20")
        self.assertEqual(hit.groups(), ("04", "29", "Deposit", "$31.20"))

    def test_wrapped_row_joins_to_one_match(self):
        joined = " ".join(["04/30 The Insurance Co.", "Monthly Deposit 40.76"])
        hit = wf.ROW.match(joined)
        self.assertEqual(hit.group(3), "The Insurance Co. Monthly Deposit")
        self.assertEqual(hit.group(4), "40.76")

    def test_a_total_line_is_not_a_row(self):
        self.assertIsNone(wf.ROW.match("Total other withdrawals $628.19"))

    def test_check_pair_reads_both_columns_on_one_line(self):
        pairs = wf.CHECK_PAIR.findall("5254 04/08 21.33 5259 04/23 40.00")
        self.assertEqual(pairs, [("5254", "04", "08", "21.33"), ("5259", "04", "23", "40.00")])

    def test_check_pair_accepts_the_gap_in_sequence_marker(self):
        # A check number can carry a trailing "*" ("5265* 05/03 100.00") --
        # the CHECK_PAIR regex must still read the number and amount.
        pairs = wf.CHECK_PAIR.findall("5265* 05/03 100.00")
        self.assertEqual(pairs, [("5265", "05", "03", "100.00")])


class TestRowAssembly(unittest.TestCase):
    def rows(self, lines):
        numbered = list(enumerate(lines, start=1))
        return [(hit.group(3), hit.group(4)) for hit in wf._rows_between(numbered, 0, len(numbered))]

    def test_a_row_split_across_two_lines_is_joined(self):
        out = self.rows(["04/30 The Insurance Co.", "Monthly Deposit 40.76"])
        self.assertEqual(out, [("The Insurance Co. Monthly Deposit", "40.76")])

    def test_a_new_date_line_flushes_an_incomplete_pending_row(self):
        # If a row never completes (malformed input), the next "MM/DD" line
        # must start fresh rather than glue itself onto the orphaned buffer.
        out = self.rows(["04/04 Orphaned fragment with no amount", "04/05 Complete row 12.34"])
        self.assertEqual(out, [("Complete row", "12.34")])

    def test_section_dots_and_headers_are_skipped(self):
        out = self.rows(["Date Description Amount", "." * 80, "05/01 Single Line 5.00"])
        self.assertEqual(out, [("Single Line", "5.00")])


class TestFindAnchor(unittest.TestCase):
    def test_prefix_match_finds_a_total_line(self):
        lines = [(1, "Total checks $553.69")]
        self.assertEqual(wf._find(lines, "Total checks"), 0)

    def test_does_not_confuse_the_activity_summary_line_with_the_section_header(self):
        # Regression: "Deposits and interest 1,291.34" (the Activity Summary
        # line) is a *prefix match* for the bare label "Deposits and interest"
        # (the Activity Detail section header) -- anchoring after "Activity
        # detail" is what tells them apart.
        lines = [
            (1, "Deposits and interest 1,291.34"),   # Activity Summary -- not the header
            (2, "Activity detail"),
            (3, "Deposits and interest"),             # the real section header
        ]
        detail = wf._find(lines, "Activity detail")
        self.assertEqual(wf._find(lines, "Deposits and interest", after=max(detail, 0)), 2)


class TestYearResolution(unittest.TestCase):
    def test_same_year_as_closing(self):
        self.assertEqual(wf._year_for(4, 3, date(2002, 5, 3)), date(2002, 4, 3))

    def test_a_december_opening_before_a_january_close_is_the_prior_year(self):
        self.assertEqual(wf._year_for(12, 5, date(2026, 1, 3)), date(2025, 12, 5))


class TestValidation(unittest.TestCase):
    def make(self, txns, summary):
        s = Statement(account="checking", account_last4="0000", path="x.pdf",
                      close_date=date(2002, 5, 3), period_start=date(2002, 4, 3),
                      period_end=date(2002, 5, 3), summary=dict(summary))
        for desc, amt, kind in txns:
            s.txns.append(Txn(account="checking", account_last4="0000",
                              date=date(2002, 4, 15), description=desc, amount=amt, kind=kind,
                              statement_close=date(2002, 5, 3),
                              period_start=date(2002, 4, 3), period_end=date(2002, 5, 3),
                              source_file="x.pdf", source_line=1))
        wf._validate(s)
        return s

    def test_consistent_statement_passes(self):
        s = self.make(
            [("Check 100", -50.0, "withdrawal"), ("Some Store", -20.0, "withdrawal"),
             ("Deposit", 100.0, "deposit")],
            {"beginning_balance": 1000.0, "ending_balance": 1030.0,
             "checks": 50.0, "other_withdrawals": 20.0, "withdrawals": 70.0, "deposits": 100.0},
        )
        self.assertTrue(s.ok, [c.name for c in s.checks if not c.ok])

    def test_a_check_miscounted_as_an_other_withdrawal_is_caught(self):
        # "Check 100" only counts toward checks_total because of its
        # description prefix -- if that ever drifted, this must fail loudly
        # rather than let the two totals silently swap.
        s = self.make(
            [("Check 100", -50.0, "withdrawal")],
            {"beginning_balance": 1000.0, "ending_balance": 950.0,
             "checks": 50.0, "other_withdrawals": 0.0},
        )
        self.assertTrue(s.ok, [c.name for c in s.checks if not c.ok])

    def test_a_dropped_row_is_caught(self):
        s = self.make(
            [("Check 100", -50.0, "withdrawal")],   # the -20.0 "Some Store" row was dropped
            {"beginning_balance": 1000.0, "ending_balance": 930.0,
             "checks": 50.0, "other_withdrawals": 20.0, "withdrawals": 70.0},
        )
        failed = {c.name for c in s.checks if not c.ok}
        self.assertIn("other_withdrawals_total", failed)
        self.assertIn("ending_balance", failed)

    def test_zero_activity_statement_still_reconciles(self):
        s = self.make([], {"beginning_balance": 500.0, "ending_balance": 500.0})
        self.assertTrue(s.ok)
        self.assertTrue(any(c.name == "ending_balance" for c in s.checks))


if __name__ == "__main__":
    unittest.main()
