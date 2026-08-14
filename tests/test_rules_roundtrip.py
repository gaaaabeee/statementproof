"""Saving a rule must take effect in the running process.

    ./.venv/bin/python -m unittest discover -s tests

The app writes rules while it is running. Five module-level tables in
merchants.py are built from the rules file at import time, and normalize() is
memoized -- so without an explicit reload a saved rule does nothing until
restart, and does it *silently*. These tests exist to make that failure loud.
"""

import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from statementproof import config, merchants, records  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "rules.json")


class RulesFileTestCase(unittest.TestCase):
    """Each test gets a private rules file; none touch a real config."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "rules.json")
        os.environ["STATEMENT_RULES"] = self.path
        merchants.reload_rules()

    def tearDown(self):
        os.environ["STATEMENT_RULES"] = FIXTURE
        merchants.reload_rules()


class TestSave(RulesFileTestCase):
    def test_creates_a_readable_file_with_the_comment_intact(self):
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        with open(self.path) as fh:
            data = json.load(fh)
        self.assertIn("_comment", data)
        self.assertEqual(data["merchants"][0]["merchant"], "Corner Cafe")

    def test_file_is_owner_only(self):
        # It names real people and payees.
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode & 0o077, 0, f"group/other bits set: {mode:o}")

    def test_unknown_sections_survive_a_write(self):
        # A newer version's section must not be dropped by an older one.
        with open(self.path, "w") as fh:
            json.dump({"payees": {}, "merchants": [], "future_section": {"keep": 1}}, fh)
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        with open(self.path) as fh:
            self.assertEqual(json.load(fh)["future_section"], {"keep": 1})

    def test_rewriting_the_same_pattern_replaces_rather_than_duplicates(self):
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Groceries")
        with open(self.path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["merchants"]), 1)
        self.assertEqual(data["merchants"][0]["category"], "Groceries")

    def test_an_invalid_regex_is_rejected_before_it_reaches_the_file(self):
        with self.assertRaises(Exception):
            config.add_merchant_rule("UNCLOSED [", "Bad", "Shopping")
        self.assertFalse(os.path.exists(self.path))

    def test_a_failed_write_leaves_no_partial_file(self):
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        with open(self.path) as fh:
            before = fh.read()
        try:
            config.save({"bad": {1, 2}})       # a set is not JSON-serializable
        except TypeError:
            pass
        with open(self.path) as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".tmp")], [])


class TestHotReload(RulesFileTestCase):
    DESC = "SOME UNKNOWN LOCAL PLACE HOUSTON TX"

    def test_a_saved_rule_applies_without_restarting(self):
        self.assertEqual(
            records.normalize(self.DESC, "checking", "withdrawal")[1], "uncategorized")

        config.add_merchant_rule("SOME UNKNOWN LOCAL PLACE", "Local Place", "Groceries")
        merchants.reload_rules()

        self.assertEqual(
            records.normalize(self.DESC, "checking", "withdrawal"),
            ("Local Place", "Groceries"))

    def test_the_memo_cache_does_not_serve_a_stale_answer(self):
        # Warm the cache with the pre-rule answer first: this is the specific
        # bug the reload exists to prevent.
        records.normalize(self.DESC, "checking", "withdrawal")
        config.add_merchant_rule("SOME UNKNOWN LOCAL PLACE", "Local Place", "Groceries")
        merchants.reload_rules()
        self.assertEqual(
            records.normalize(self.DESC, "checking", "withdrawal")[1], "Groceries")

    def test_an_ach_rule_applies_without_restarting(self):
        desc = "Example Properties DES:WEB PMTS ID:AB12CD INDN:A Person CO ID:9876543210"
        self.assertEqual(
            records.normalize(desc, "checking", "withdrawal")[1], "uncategorized")
        config.add_ach_rule("9876543210", "Rent", "Housing")
        merchants.reload_rules()
        self.assertEqual(
            records.normalize(desc, "checking", "withdrawal"), ("Rent", "Housing"))

    def test_reload_rebuilds_every_table_built_from_the_rules_file(self):
        # Guards against a table being added later and forgotten in reload().
        config.add_merchant_rule("CORNER CAFE", "Corner Cafe", "Dining & Delivery")
        config.add_ach_rule("55550000", "Utility", "Utilities")
        with open(self.path) as fh:
            raw = json.load(fh)
        raw["payees"] = {"ALEX": {"label": "Rent", "category": "Housing"}}
        config.save(raw)
        merchants.reload_rules()

        self.assertTrue(merchants.ACH_RULES)
        self.assertTrue(merchants.PAYEE_CATEGORY)
        self.assertTrue(merchants.USER_INFLOW)
        self.assertTrue(any(m == "Corner Cafe" for _, m, _ in merchants.COMPILED))
        self.assertEqual(merchants.USER_RULES["payees"]["ALEX"]["category"], "Housing")

    def test_removing_a_rule_takes_effect_too(self):
        config.add_merchant_rule("SOME UNKNOWN LOCAL PLACE", "Local Place", "Groceries")
        merchants.reload_rules()
        config.remove_merchant_rule("SOME UNKNOWN LOCAL PLACE")
        merchants.reload_rules()
        self.assertEqual(
            records.normalize(self.DESC, "checking", "withdrawal")[1], "uncategorized")


class TestLibraryPaths(unittest.TestCase):
    def test_home_is_overridable_so_tests_never_touch_a_real_library(self):
        from statementproof import paths
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STATEMENTPROOF_HOME"] = tmp
            try:
                self.assertEqual(paths.home(), os.path.abspath(tmp))
                paths.ensure_library()
                self.assertTrue(os.path.isdir(paths.statements_dir()))
                self.assertTrue(os.path.isdir(paths.out_dir()))
            finally:
                del os.environ["STATEMENTPROOF_HOME"]

    def test_library_is_not_world_readable(self):
        from statementproof import paths
        if sys.platform == "win32":
            self.skipTest("POSIX modes only")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STATEMENTPROOF_HOME"] = os.path.join(tmp, "lib")
            try:
                paths.ensure_library()
                mode = stat.S_IMODE(os.stat(paths.home()).st_mode)
                self.assertEqual(mode & 0o077, 0, f"group/other bits set: {mode:o}")
            finally:
                del os.environ["STATEMENTPROOF_HOME"]


if __name__ == "__main__":
    unittest.main()
