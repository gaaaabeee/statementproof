"""Statement format registry and detection.

A folder of PDFs is not self-describing: the file name tells you nothing
reliable, and the wrong parser applied to the right file produces numbers that
look plausible and are wrong. So every format declares how to recognize itself
from the text of page 1, and a file that matches nothing is reported as
unsupported rather than guessed at.

Adding a bank means adding one ``Format`` here plus a parser module exposing
``parse(path) -> Statement`` that validates its own output. Nothing else in the
codebase needs to change.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import boa, checking, credit
from .text import pages

# How a balance on this kind of account affects net worth. Cash up is good;
# card balance up is debt. The whole-corpus reconciliation depends on this.
ASSET, LIABILITY = 1, -1


@dataclass
class Format:
    name: str                       # stable id, e.g. "chase_checking"
    label: str                      # human readable, shown in errors
    account_kind: str               # "checking" | "credit"
    polarity: int                   # ASSET or LIABILITY
    required: list                  # at least one of these must appear
    markers: list                   # each adds confidence
    parse: Callable

    def score(self, text: str) -> int:
        """0 if this format is ruled out, else 1 + the number of markers hit."""
        if not any(r in text for r in self.required):
            return 0
        return 1 + sum(1 for m in self.markers if m in text)


FORMATS: list = [
    Format(
        name="chase_checking",
        label="Chase personal checking",
        account_kind="checking",
        polarity=ASSET,
        required=["CHECKING SUMMARY", "Chase Total Checking"],
        markers=["JPMorgan Chase Bank", "TRANSACTION DETAIL", "Service Center",
                 "Account Number:"],
        parse=checking.parse,
    ),
    Format(
        name="chase_credit",
        label="Chase credit card",
        account_kind="credit",
        polarity=LIABILITY,
        required=["Opening/Closing Date"],
        markers=["Previous Balance", "Minimum Payment Due", "chase.com/cardhelp",
                 "ACCOUNT SUMMARY"],
        parse=credit.parse,
    ),
    Format(
        name="boa_checking",
        label="Bank of America personal checking",
        account_kind="checking",
        polarity=ASSET,
        required=["bankofamerica.com", "Bank of America, N.A."],
        markers=["Account summary", "Beginning balance on", "Ending balance on",
                 "Customer service: 1.800.432.1000"],
        parse=boa.parse,
    ),
]

BY_NAME = {f.name: f for f in FORMATS}


def _account_polarity() -> dict:
    """Map account kind -> ASSET/LIABILITY, refusing to guess on disagreement.

    Several banks supply the same kind of account, so this cannot be keyed by
    format. Building it as a dict comprehension over FORMATS would silently keep
    whichever format was declared last -- and a wrong polarity flips the sign of
    a whole account in the net-position check without failing anything else.
    """
    out = {}
    for f in FORMATS:
        if out.setdefault(f.account_kind, f.polarity) != f.polarity:
            raise ValueError(
                f"formats disagree on whether {f.account_kind!r} is an asset or a "
                f"liability; {f.name} conflicts with an earlier format"
            )
    return out


ACCOUNT_POLARITY = _account_polarity()


@dataclass
class Detection:
    path: str
    format: Optional[Format] = None
    score: int = 0
    error: str = ""
    runners_up: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.format is not None

    def describe(self) -> str:
        name = os.path.basename(self.path)
        if self.ok:
            return f"{name}: {self.format.label} (confidence {self.score})"
        if self.error:
            return f"{name}: unreadable -- {self.error}"
        return (f"{name}: no supported format matched. Supported: "
                + ", ".join(f.label for f in FORMATS))


# Some statements open with an insert or notice page, so the summary block that
# identifies the product lands on page 2. Scanning a few pages costs nothing and
# avoids rejecting a perfectly supported statement over a cover sheet.
DETECT_PAGES = 3


def detect(path: str) -> Detection:
    """Identify the statement format of one PDF from its opening pages."""
    try:
        # pypdf logs its own complaints about malformed files; we report them
        # ourselves, with the filename attached, so keep its noise out of the way.
        level = logging.getLogger("pypdf").level
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        try:
            page_texts = pages(path)
        finally:
            logging.getLogger("pypdf").setLevel(level)
    except Exception as exc:                       # encrypted, corrupt, not a PDF
        return Detection(path, error=f"{type(exc).__name__}: {exc}")

    if not page_texts:
        return Detection(path, error="PDF has no pages")

    text = "\n".join(page_texts[:DETECT_PAGES])
    if not text.strip():
        return Detection(
            path,
            error=f"no extractable text in the first {DETECT_PAGES} pages "
                  "(a scanned image? OCR is not supported)",
        )

    scored = sorted(((f.score(text), f) for f in FORMATS), key=lambda p: -p[0])
    best_score, best = scored[0]
    if best_score == 0:
        return Detection(path)
    return Detection(
        path, format=best, score=best_score,
        runners_up=[f.label for s, f in scored[1:] if s > 0],
    )
