"""Tests for the categorization eval harness itself, plus a regression floor.

    ./.venv/bin/python -m unittest discover -s tests

Two different things are being tested here, and they must not be confused:

* ``TestScoring`` checks the *harness's arithmetic* against a synthetic
  normalize() stub -- it has nothing to do with real categorization.
* ``TestShippedRuleset`` runs the real harness against the real fixture and
  asserts 100% -- because every expected_* value in eval_set.jsonl was
  computed from the shipped ruleset in the first place (see its header
  comment), a drop below 100% here means a rule regressed, not that the
  fixture needs updating. If a change to merchants.py is intentional, update
  the fixture with statementproof.eval and confirm the new numbers by hand
  before committing them.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from statementproof import eval as ev  # noqa: E402


class TestScoring(unittest.TestCase):
    """Harness arithmetic, isolated from the real ruleset with a stub."""

    def stub(self, description, account, kind):
        table = {
            "KNOWN": ("Known Co", "Shopping"),
            "WRONG CATEGORY": ("Wrong Co", "Dining & Delivery"),
            "WRONG MERCHANT": ("Not Expected Co", "Shopping"),
            "UNKNOWN": ("Unknown Co", "uncategorized"),
        }
        return table[description]

    def cases(self):
        return [
            ev.Case("KNOWN", "credit", "purchase", "Known Co", "Shopping"),
            ev.Case("WRONG CATEGORY", "credit", "purchase", "Wrong Co", "Groceries"),
            ev.Case("WRONG MERCHANT", "credit", "purchase", "Expected Co", "Shopping"),
            ev.Case("UNKNOWN", "credit", "purchase", "Unknown Co", "uncategorized"),
        ]

    def test_exact_match_counts_toward_everything(self):
        result = ev.run([self.cases()[0]], self.stub)
        self.assertEqual(result.exact_matches, 1)
        self.assertEqual(result.accuracy, 1.0)
        self.assertEqual(result.coverage, 1.0)

    def test_wrong_category_is_a_miss_but_still_a_merchant_match(self):
        result = ev.run([self.cases()[1]], self.stub)
        self.assertEqual(result.merchant_matches, 1)
        self.assertEqual(result.category_matches, 0)
        self.assertEqual(result.exact_matches, 0)
        self.assertEqual(len(result.misses), 1)

    def test_a_wrong_match_still_counts_as_coverage(self):
        # Coverage only asks "did this fall through to uncategorized" -- a row
        # that matched the wrong rule is covered but not accurate. That gap is
        # exactly why accuracy is tracked separately.
        result = ev.run([self.cases()[1]], self.stub)
        self.assertEqual(result.coverable, 1)
        self.assertEqual(result.covered, 1)
        self.assertEqual(result.accuracy, 0.0)

    def test_expected_uncategorized_is_excluded_from_coverage(self):
        result = ev.run([self.cases()[3]], self.stub)
        self.assertEqual(result.coverable, 0)
        self.assertEqual(result.coverage, 1.0)   # nothing to cover, not a failure
        self.assertEqual(result.exact_matches, 1)

    def test_mixed_batch_totals(self):
        result = ev.run(self.cases(), self.stub)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.exact_matches, 2)   # KNOWN, UNKNOWN
        self.assertEqual(result.coverable, 3)       # excludes UNKNOWN
        self.assertEqual(result.covered, 3)         # WRONG MERCHANT still covered
        self.assertEqual(len(result.misses), 2)

    def test_empty_case_list_does_not_divide_by_zero(self):
        result = ev.run([], self.stub)
        self.assertEqual(result.accuracy, 1.0)
        self.assertEqual(result.coverage, 1.0)


class TestLoadCases(unittest.TestCase):
    def test_blank_lines_and_comments_are_skipped(self):
        path = os.path.join(HERE, "fixtures", "eval_set.jsonl")
        cases = ev.load_cases(path)
        self.assertGreater(len(cases), 0)
        self.assertTrue(all(isinstance(c, ev.Case) for c in cases))

    def test_malformed_json_names_the_line(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write('{"description": "ok", "account": "credit", "kind": "purchase", '
                     '"expected_merchant": "A", "expected_category": "B"}\n')
            fh.write("not json\n")
            path = fh.name
        try:
            with self.assertRaises(SystemExit) as ctx:
                ev.load_cases(path)
            self.assertIn(":2:", str(ctx.exception))
        finally:
            os.unlink(path)


class TestShippedRuleset(unittest.TestCase):
    """The real harness against the real fixture -- a regression floor.

    See the module docstring: a drop below 100% here means merchants.py
    regressed against its own previously-verified behavior, not that this
    test is wrong.
    """

    def setUp(self):
        # reload_rules() rewrites shared module state, not just this test's
        # view of it -- other test files import the same merchants module and
        # expect the suite-wide fixture (tests/fixtures/rules.json) to still
        # be loaded when they run. Save and restore around the swap to
        # DEFAULT_RULES so this test can't leak its empty ruleset onward.
        self.prior_rules_path = os.environ.get("STATEMENT_RULES")

    def tearDown(self):
        from statementproof import merchants
        if self.prior_rules_path is None:
            os.environ.pop("STATEMENT_RULES", None)
        else:
            os.environ["STATEMENT_RULES"] = self.prior_rules_path
        merchants.reload_rules()

    def test_shipped_ruleset_scores_100_percent_on_its_own_eval_set(self):
        os.environ["STATEMENT_RULES"] = ev.DEFAULT_RULES
        from statementproof import merchants
        merchants.reload_rules()

        cases = ev.load_cases(ev.DEFAULT_FIXTURE)
        result = ev.run(cases, merchants.normalize)

        if result.misses:
            detail = "\n".join(
                f"  {m.case.description!r}: expected "
                f"({m.case.expected_merchant!r}, {m.case.expected_category!r}), "
                f"got ({m.got_merchant!r}, {m.got_category!r})"
                for m in result.misses
            )
            self.fail(f"{len(result.misses)} case(s) regressed:\n{detail}")

        self.assertEqual(result.accuracy, 1.0)
        self.assertEqual(result.coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
