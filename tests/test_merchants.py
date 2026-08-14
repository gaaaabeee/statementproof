"""Tests for descriptor cleanup and categorization.

    ./.venv/bin/python -m unittest discover -s tests

Cases mirror the *shapes* that real Chase statements produce -- including the
ones that broke earlier versions of the parser -- with every name, account
number, phone number and trace ID replaced by an invented placeholder. No real
person, merchant relationship or account appears in this file.

Personal rules live in a user config file, so the suite points STATEMENT_RULES
at a fixture before importing the parser. Tests therefore never read, and never
depend on, whatever the developer happens to have configured locally.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statementproof.merchants import clean, normalize, suggest_category  # noqa: E402


class TestClean(unittest.TestCase):
    def test_strips_square_prefix_city_and_state(self):
        self.assertEqual(clean("SQ *TACOS EXAMPLE GRILL Sometown TX"), "TACOS EXAMPLE GRILL")

    def test_strips_toast_prefix_and_truncated_location(self):
        # "- EA" is a truncated location fragment, not part of the name.
        self.assertEqual(clean("TST* EXAMPLE ICE HOUSE - EA SOMETOWN TX"), "EXAMPLE ICE HOUSE")

    def test_strips_store_number_and_phone(self):
        self.assertEqual(clean("TIM HORTONS #000000 SOMETOWN TX"), "TIM HORTONS")
        self.assertEqual(clean("PROGRESSIVE INS 000-000-0000 OH"), "PROGRESSIVE INS")

    def test_strips_checking_channel_prefix_and_card_suffix(self):
        self.assertEqual(
            clean("Card Purchase 03/05 Example Cafe TX Card 0000"), "Example Cafe"
        )

    def test_domain_only_name_survives_url_stripping(self):
        # Stripping every URL token would leave nothing at all.
        self.assertEqual(clean("NETFLIX.COM NETFLIX.COM CA"), "NETFLIX")
        self.assertEqual(clean("POTBELLY POTBELLY.COM/ TX"), "POTBELLY")


class TestNormalize(unittest.TestCase):
    def n(self, desc, account="credit", kind="purchase"):
        return normalize(desc, account, kind)

    def test_variants_collapse_to_one_merchant(self):
        # Four spellings of the same gas station across 20 months.
        for desc in [
            "SHELL OIL 00000000000 SOMETOWN TX",
            "SHELL 00000000000 SOMETOWN TX",
            "SHELL OIL 00000000001 SOMETOWN TX",
            "SHELL 00000000002 SOMETOWN TX",
        ]:
            self.assertEqual(self.n(desc)[0], "Shell", desc)

    def test_playstation_casing_variants(self):
        for desc in ["PlayStation Network 000-0000000 CA",
                     "PLAYSTATION NETWORK 000-000-0000 CA"]:
            self.assertEqual(self.n(desc), ("PlayStation", "Entertainment"))

    def test_aggregator_is_the_merchant_not_the_suffix(self):
        # Stripping the prefix would leave "Ride Wed 11pm" / "Doordash Popeyeslo".
        self.assertEqual(self.n("LYFT *RIDE WED 11PM LYFT.COM CA"), ("Lyft", "Transport"))
        self.assertEqual(
            self.n("DD *DOORDASH POPEYESLO 000-000-0000 CA"), ("DoorDash", "Dining & Delivery")
        )

    def test_kind_overrides_name_matching(self):
        self.assertEqual(
            self.n("PURCHASE INTEREST CHARGE", kind="interest"),
            ("Chase card interest", "Fees & Interest"),
        )
        self.assertEqual(
            self.n("FANDUELSBKPRIMARY 0000000000 NJ", kind="cash_advance"),
            ("Cash advance", "Cash & ATM"),
        )

    def test_refund_keeps_merchant_but_not_category(self):
        merchant, category = self.n("AMAZON MKTPL*AA0AA0AA0 Amzn.com/bill WA", kind="credit")
        self.assertEqual(merchant, "Amazon")
        self.assertEqual(category, "Refunds")

    def test_card_payment_is_a_transfer_on_both_sides(self):
        self.assertEqual(
            self.n("Payment Thank You-Mobile", kind="payment")[1], "Transfers"
        )
        self.assertEqual(
            self.n("07/16 Payment To Chase Card Ending IN 0000",
                   account="checking", kind="withdrawal")[1],
            "Transfers",
        )

    def test_processor_implies_category_for_unknown_merchants(self):
        # Toast serves restaurants only; Shopify checkouts are online retail.
        self.assertEqual(self.n("TST*OFF THE RECORD Sometown TX")[1], "Dining & Delivery")
        self.assertEqual(self.n("SP EXAMPLESHOP.NE EXAMPLESHOP NY")[1], "Shopping")

    def test_keyword_hint_catches_the_long_tail(self):
        self.assertEqual(self.n("GAZEBO CAFE SOMETOWN LA")[1], "Dining & Delivery")

    def test_p2p_sent_is_spending_classified_by_counterparty(self):
        # Zelle is a rail, not a merchant: money sent over it is gone, and the
        # counterparty decides what it bought. Treating the rail itself as a
        # transfer hides standing obligations like rent from every total.
        self.assertEqual(
            self.n("Zelle Payment To Alex Jpm99Xx0000A", "checking", "withdrawal"),
            ("Rent (Alex)", "Housing"),
        )
        self.assertEqual(
            self.n("Zelle Payment To Robin Jpm99Xx0000B", "checking", "withdrawal"),
            ("Cleaning (Robin)", "Household"),
        )
        # An unconfirmed counterparty stays generic rather than being guessed at.
        self.assertEqual(
            self.n("Zelle Payment To Casey Jpm99Xx0000C", "checking", "withdrawal"),
            ("To Casey", "People & Services"),
        )

    def test_p2p_received_is_a_reimbursement_not_income(self):
        # Money coming back from a person offsets spending; counting it as
        # income would inflate earnings by every repayment received.
        self.assertEqual(
            self.n("Zelle Payment From Jordan T Rivera 20000000000", "checking", "deposit"),
            ("Zelle received", "Reimbursements"),
        )

    def test_inflows_are_separated_by_what_they_actually_are(self):
        cases = [
            ("Acme Corp Payroll PPD ID: 0000000000", "Income"),
            ("Irs Treas 310 Tax Ref PPD ID: 0000000000", "Income"),
            ("Truist Ck Webxfr P2P Pat Doe Web ID: 0000000000", "Transfers"),
            ("Ticketmaster Res 1216-th003 200000000000000 CCD ID: 0000000000", "Reimbursements"),
            ("Deposit 0000000000", "One-off deposits"),
        ]
        for desc, expected in cases:
            self.assertEqual(self.n(desc, "checking", "deposit")[1], expected, desc)

    def test_wire_to_a_dealership_is_a_purchase_not_a_transfer(self):
        merchant, category = self.n(
            "06/12 Online Domestic Wire Transfer Via: Some Bank Na/000000000 "
            "A/C: Some Dealership City ST 00000 US Ref: Down Payment For Car",
            "checking", "withdrawal",
        )
        self.assertEqual(category, "Auto")   # via the fixture's user rule
        self.assertEqual(self.n("06/12 Online Domestic Wire Fee", "checking", "withdrawal")[1],
                         "Fees & Interest")

    def test_brand_punctuation_variants_all_match(self):
        # Walmart was missed for a hyphen: the rule said WALMART and the
        # statement said WAL-MART. Punctuation variants are the cheapest way to
        # lose a national brand, so they are pinned here.
        for desc in ("WAL-MART #0915 STAFFORD TX", "WALMART SUPERCENTER HOUSTON TX",
                     "WM SUPERCENTER #123 HOUSTON TX"):
            self.assertEqual(self.n(desc, "checking", "withdrawal")[0], "Walmart", desc)

    def test_national_chains_are_recognised(self):
        cases = [
            ("WENDY'S DIGITAL DUBLIN OH", "Dining & Delivery"),
            ("DOMINO'S 6684 HOUSTON TX", "Dining & Delivery"),
            ("RAISING CANES 0223 HOUSTON TX", "Dining & Delivery"),
            ("COSTCO WHSE #1018 HOUSTON TX", "Groceries"),
            ("BASS PRO SPRIN HOUSTON TX", "Shopping"),
            ("SOUTHWES 8004359792 TX", "Travel"),
            ("TX DPS DL OFFICE AUSTIN TX", "Government & Taxes"),
            ("HOPDODDY BURGER BAR HOUSTON TX", "Dining & Delivery"),
            ("PMUSA 000000 SOMETOWN 000-0000000 GA", "Shopping"),
        ]
        for desc, expected in cases:
            self.assertEqual(self.n(desc, "checking", "withdrawal")[1], expected, desc)

    def test_with_pin_channel_prefix_is_fully_stripped(self):
        # Regex alternation matches the first branch that fits, not the
        # longest -- "Card Purchase" alone used to win over "Card Purchase
        # With Pin", leaving "With Pin 03/06" stuck to the front of the name.
        self.assertEqual(
            self.n("Card Purchase With Pin 03/06 Example Cafe TX Card 0000",
                   "checking", "withdrawal"),
            ("Example Cafe", "Dining & Delivery"),
        )

    def test_p2p_rail_wrapped_in_a_payment_sent_channel_prefix_is_recognised(self):
        # Chase wraps some P2P rails in the same "Payment Sent MM/DD" channel
        # prefix as a card payment. P2P_SENT is anchored at the start of the
        # string, so leaving that prefix on hid the rail entirely and the row
        # fell through to uncategorized instead of being recognised as spend.
        self.assertEqual(
            self.n("Payment Sent 01/19 Apple Cash Sent Money Some Person CA Card 0000",
                   "checking", "withdrawal"),
            ("To Some Person", "People & Services"),
        )

    def test_apple_cash_truncated_to_mone_still_matches(self):
        # Some statements truncate "Money" to "Mone"; the regex must accept
        # both spellings rather than leaving a stray "Y" on the payee name.
        self.assertEqual(
            self.n("Payment Sent 01/19 Apple Cash Sent Mone Some Person CA Card 0000",
                   "checking", "withdrawal"),
            ("To Some Person", "People & Services"),
        )

    def test_unknown_merchant_is_left_uncategorized_not_guessed(self):
        merchant, category = self.n("UNKNOWN VENDOR LLC SOMETOWN TX")
        self.assertEqual(category, "uncategorized")
        self.assertEqual(merchant, "Unknown Vendor LLC")


class TestSuggestCategory(unittest.TestCase):
    """suggest_category() is advisory-only -- it must never be confident about
    an opaque proper noun, and must never be consulted by normalize() itself.
    """

    def test_a_recognisable_keyword_gets_a_guess(self):
        self.assertEqual(suggest_category("EXAMPLE PATISSERIE HOUSTON TX"), "Dining & Delivery")
        self.assertEqual(suggest_category("SOMETOWN FLORIST"), "Shopping")
        self.assertEqual(suggest_category("RIVER OAKS CAR WASH"), "Auto")

    def test_an_opaque_proper_noun_gets_no_guess(self):
        # The whole point: most of the long tail has no keyword in it at all,
        # and this must say so rather than invent one.
        self.assertIsNone(suggest_category("FULLER LIFE 832-848-0870 TX"))
        self.assertIsNone(suggest_category("STEP IN HOUSTON TX"))

    def test_suggestions_never_leak_into_normalize(self):
        # A word only SUGGEST_HINTS recognises (not CATEGORY_HINTS) must still
        # come back uncategorized from normalize() -- the guess is advisory
        # only and must never silently become the real answer.
        desc = "SOMETOWN FLORIST HOUSTON TX"
        self.assertIsNotNone(suggest_category(desc))
        self.assertEqual(normalize(desc, "credit", "purchase")[1], "uncategorized")


if __name__ == "__main__":
    unittest.main()
