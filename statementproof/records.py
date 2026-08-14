"""Data types shared by the checking and credit parsers."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from functools import lru_cache
from typing import Optional

from .merchants import normalize as _normalize


@lru_cache(maxsize=4096)
def normalize(description: str, account: str, kind: str) -> tuple[str, str]:
    """Cached wrapper -- descriptors repeat heavily across statements."""
    return _normalize(description, account, kind)


# Column order used for the transaction CSV.
TXN_FIELDS = [
    "account",
    "account_last4",
    "date",
    "merchant",
    "category",
    "description",
    "amount",
    "signed",
    "kind",
    "balance",
    "statement_close",
    "period_start",
    "period_end",
    "source_file",
    "source_line",
]


@dataclass
class Txn:
    """One posted transaction.

    ``amount`` is exactly what the statement prints. That means the sign
    convention differs between the two account types, which is why ``signed``
    exists:

    * checking -- printed amount is already signed from the account's point of
      view (deposit positive, withdrawal negative), so ``signed == amount``.
    * credit   -- printed amount is signed from the *card balance's* point of
      view (a purchase raises the balance and prints positive; a payment
      lowers it and prints negative). ``signed == -amount`` flips that back to
      the cardholder's point of view.

    With that flip, a card payment appears as a negative in checking and an
    equal positive on the card, so transfers net to zero and the two accounts
    can be summed without double counting. See README.
    """

    account: str            # "checking" | "credit"
    account_last4: str
    date: date
    description: str
    amount: float
    kind: str               # deposit|withdrawal|purchase|payment|fee|interest
    statement_close: date
    period_start: date
    period_end: date
    source_file: str
    source_line: int
    balance: Optional[float] = None   # checking only: running balance after txn
    # The merchant portion, with this bank's channel wrapper removed. Only a
    # parser knows its own envelope, so only a parser can strip it -- a shared
    # cleanup that tried to handle every bank's wrapper over-stripped some of
    # them. Empty means "nothing to remove", and the raw description is used.
    descriptor: str = ""

    @property
    def signed(self) -> float:
        return self.amount if self.account == "checking" else -self.amount

    @property
    def match_text(self) -> str:
        """What the categorizer reads: the unwrapped descriptor if there is one."""
        return self.descriptor or self.description

    @property
    def merchant(self) -> str:
        return normalize(self.match_text, self.account, self.kind)[0]

    @property
    def category(self) -> str:
        return normalize(self.match_text, self.account, self.kind)[1]

    def as_row(self) -> dict:
        d = asdict(self)
        d["signed"] = round(self.signed, 2)
        d["merchant"], d["category"] = normalize(self.match_text, self.account, self.kind)
        d["date"] = self.date.isoformat()
        d["statement_close"] = self.statement_close.isoformat()
        d["period_start"] = self.period_start.isoformat()
        d["period_end"] = self.period_end.isoformat()
        return {k: d[k] for k in TXN_FIELDS}


@dataclass
class Statement:
    """One parsed statement plus the outcome of its self-checks."""

    account: str
    account_last4: str
    path: str
    close_date: date
    period_start: date
    period_end: date
    txns: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)   # totals as printed
    checks: list = field(default_factory=list)    # list[Check]
    unparsed: list = field(default_factory=list)  # (line_no, text)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def key(self) -> tuple:
        """Identifies one real-world account across all of its statements."""
        return (self.account, self.account_last4)

    # Opening and closing balances print under different labels per account
    # type. Exposing them uniformly is what lets the cross-statement checks
    # work for any number of accounts of any kind, rather than assuming
    # exactly one checking and one card.
    @property
    def opening_balance(self) -> Optional[float]:
        for k in ("beginning_balance", "previous_balance"):
            if k in self.summary:
                return self.summary[k]
        return None

    @property
    def closing_balance(self) -> Optional[float]:
        for k in ("ending_balance", "new_balance"):
            if k in self.summary:
                return self.summary[k]
        return None


@dataclass
class Check:
    """A single validation of parsed data against a number the statement prints."""

    name: str
    expected: float
    actual: float
    tolerance: float = 0.005

    @property
    def delta(self) -> float:
        return self.actual - self.expected

    @property
    def ok(self) -> bool:
        return abs(self.delta) <= self.tolerance
