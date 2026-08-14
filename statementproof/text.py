"""PDF text extraction and the small shared helpers both parsers need."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from pypdf import PdfReader

_WS = re.compile(r"[ \t\xa0]+")

# Matches money as Chase prints it: optional sign, optional $, optional
# thousands separators, and a possibly-absent leading zero (".18" is real --
# it shows up as a cash-advance interest charge).
MONEY = r"-?\$?-?(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}"


def pages(path: str) -> list[str]:
    """Return each page's text with runs of whitespace collapsed."""
    out = []
    for page in PdfReader(path).pages:
        out.append(_WS.sub(" ", page.extract_text() or ""))
    return out


def numbered_lines(page_texts: list[str]) -> Iterator[tuple[int, str]]:
    """Yield (global_line_no, stripped_line) across all pages, 1-indexed."""
    n = 0
    for text in page_texts:
        for line in text.split("\n"):
            n += 1
            line = line.strip()
            if line:
                yield n, line


def money(s: str) -> float:
    """Parse a Chase money string to float. Handles '$', ',', '.18', '-'."""
    s = s.strip().replace(",", "").replace("$", "").replace(" ", "")
    neg = s.startswith("-")
    s = s.lstrip("-").lstrip("+")
    if s.startswith("."):
        s = "0" + s
    val = float(s)
    return -val if neg else val


def resolve_year(mm: int, dd: int, start: date, end: date, slack_days: int = 45) -> date:
    """Turn a bare MM/DD into a full date using the statement period.

    Statement rows omit the year, and a cycle can straddle New Year (e.g. the
    Dec 3 - Jan 2 card cycle), so the year is whichever of the period's two
    candidate years lands the date closest to the period. Slack is allowed
    because a card's *transaction* date can precede the cycle open by a few
    days -- the posting date is what put it in this statement.
    """
    best: Optional[date] = None
    best_cost = None
    for year in {start.year, end.year}:
        try:
            cand = date(year, mm, dd)
        except ValueError:      # e.g. 02/29 in a non-leap year
            continue
        if start <= cand <= end:
            cost = 0
        elif cand < start:
            cost = (start - cand).days
        else:
            cost = (cand - end).days
        if best_cost is None or cost < best_cost:
            best, best_cost = cand, cost
    if best is None:
        raise ValueError(f"impossible date {mm:02d}/{dd:02d} in {start}..{end}")
    if best_cost > slack_days:
        raise ValueError(
            f"date {best} is {best_cost}d outside period {start}..{end}"
        )
    return best
