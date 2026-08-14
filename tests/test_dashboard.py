"""Tests for statementproof.dashboard.find_recurring().

    ./.venv/bin/python -m unittest discover -s tests

The insight layer shows the drift between a recurring charge's first and last
amount as a factual claim ("Progressive went from $120.83 to $276.91"), so
those two fields must be exactly the first and last row in the merchant's own
history -- not the median, not an average, not the current statement's value.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from statementproof.dashboard import find_recurring  # noqa: E402


def row(merchant, date, amount, category="Insurance"):
    return {"merchant": merchant, "date": date, "month": date[:7],
            "signed": -amount, "category": category}


class TestFindRecurring(unittest.TestCase):
    def test_first_and_last_amount_are_the_actual_first_and_last_charge(self):
        rows = [
            row("Progressive (insurance)", "2025-01-15", 120.83),
            row("Progressive (insurance)", "2025-02-15", 120.83),
            row("Progressive (insurance)", "2025-03-15", 120.83),
            row("Progressive (insurance)", "2025-04-15", 276.91),
            row("Progressive (insurance)", "2025-05-15", 276.91),
        ]
        found = find_recurring(rows, "2025-06-01")
        self.assertEqual(len(found), 1)
        r = found[0]
        self.assertEqual(r["first_amount"], 120.83)
        self.assertEqual(r["last_amount"], 276.91)
        # typical (median) must not be confused with either endpoint.
        self.assertEqual(r["typical"], 120.83)

    def test_amounts_are_taken_in_date_order_not_input_order(self):
        rows = [
            row("Utility Co", "2025-03-01", 90.00),
            row("Utility Co", "2025-01-01", 50.00),
            row("Utility Co", "2025-04-01", 95.00),
            row("Utility Co", "2025-02-01", 60.00),
        ]
        found = find_recurring(rows, "2025-05-01")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["first_amount"], 50.00)
        self.assertEqual(found[0]["last_amount"], 95.00)

    def test_a_stable_price_has_equal_first_and_last_amount(self):
        rows = [row("Netflix", f"2025-0{m}-01", 15.49) for m in range(1, 5)]
        found = find_recurring(rows, "2025-05-01")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["first_amount"], found[0]["last_amount"])

    def test_an_irregular_merchant_is_not_flagged_as_recurring(self):
        rows = [
            row("Random Diner", "2025-01-03", 22.00),
            row("Random Diner", "2025-01-19", 31.00),
            row("Random Diner", "2025-03-02", 18.00),
            row("Random Diner", "2025-06-14", 44.00),
        ]
        found = find_recurring(rows, "2025-07-01")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
