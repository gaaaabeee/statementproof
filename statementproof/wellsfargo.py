"""Parser for Wells Fargo personal checking statements.

EXPERIMENTAL. Built from Wells Fargo's own official specimen statement
(wellsfargo.com/assets/pdf/personal/help/tester.pdf) rather than a real
account -- and that specimen is dated May 3, 2002. Wells Fargo has redesigned
online banking more than once since then; there is a real chance a current
statement's layout, section names, or detection phrases have changed. This is
not a guess about what the layout might be -- every regex here was built
against real, verified text -- but it is unverified against anything printed
in the last two decades. Detection is conservative for exactly this reason: if
it doesn't match a current statement, that's an honest "unsupported," the same
as any other unrecognized file, not a wrong number. See CONTRIBUTING.md.

Layout, from the specimen:

1. **Section-and-summary proof**, like ``credit.py`` and ``boa.py`` -- there
   is no running balance per row. Five independent checks: the checks table,
   the other-withdrawals table and the deposits table each reconcile against
   their own printed "Total ..." line, the two totals sum to the printed
   "Total withdrawals", and the opening balance plus the net of every parsed
   row reproduces the printed closing balance.

   The statement also prints a "Daily balance summary" -- one row per day with
   activity. It is **not** used for validation: on the specimen it disagrees
   with the transaction-level detail by exactly $60.00 on one date before
   self-correcting, which means the specimen itself doesn't fully reconcile at
   that granularity. The section totals above do reconcile exactly (verified
   by hand before writing this parser), so they carry the whole proof instead.
2. **Default-mode extraction**, not layout mode. Layout mode reorders words
   within a wrapped row on this specimen (e.g. "Smith Cable Systems Basic
   Service" instead of "Cable Systems Basic Service" / "Smith"), which is the
   opposite of Bank of America's statements.
3. **Rows wrap the same way Chase checking's do**: a row starts on a line
   beginning "MM/DD ", may continue onto one or more following lines, and the
   amount lands at the end of whichever line finishes it. Reuses the same
   line-buffering approach as ``checking.py``.
4. **The checks table** is two columns of (number, date, amount) triples per
   line, not the wrapping row shape -- a paper check has no merchant text, so
   it is recorded as "Check <number>" and left for the categorizer to leave
   uncategorized, same as any other unidentified row.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime

from .records import Check, Statement, Txn
from .text import MONEY, money, numbered_lines, pages

STATEMENT_DATE = re.compile(r"Statement Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
ACCOUNT = re.compile(r"Account Number:\s*([\d\-]+)")
BALANCE_ON = re.compile(rf"Balance on (\d{{2}})/(\d{{2}})\s+({MONEY})")

TOTAL_CHECKS = re.compile(rf"Total checks\s+({MONEY})")
TOTAL_OTHER_WITHDRAWALS = re.compile(rf"Total other withdrawals\s+({MONEY})")
TOTAL_WITHDRAWALS = re.compile(rf"Total withdrawals\s+({MONEY})")
TOTAL_DEPOSITS = re.compile(rf"Total deposits and interest\s+({MONEY})")

CHECK_PAIR = re.compile(rf"(\d{{3,6}})\*?\s+(\d{{2}})/(\d{{2}})\s+({MONEY})")
ROW = re.compile(rf"^(\d{{2}})/(\d{{2}})\s+(.+?)\s+({MONEY})$")

SECTION_DOTS = re.compile(r"^\.{5,}\s*\.{0,}$")   # one or two dotted rules per line


def _year_for(mm: int, dd: int, close: date) -> date:
    """A bare opening-balance MM/DD, resolved against the statement date.

    This specimen never prints the opening date's year -- only "Balance on
    04/03" -- so the year is inferred the same way a cycle-crossing December
    statement would be: if the month is after the closing month, it must be
    the prior year.
    """
    year = close.year - 1 if mm > close.month else close.year
    return date(year, mm, dd)


def _rows_between(lines: list[tuple[int, str]], start: int, end: int):
    """Assemble wrapped rows between two line indices, Chase-checking style.

    A row starting "MM/DD " may continue onto following lines; the amount
    lands at the end of whichever line completes it. Buffered exactly like
    ``checking.py``'s transaction table, because the wrap shape is identical.
    """
    pending: list[str] = []
    for _, line in lines[start:end]:
        if SECTION_DOTS.match(line) or not line:
            continue
        hit = ROW.match(line)
        if hit:
            pending.clear()
            yield hit
            continue
        starts_row = line[:6].count("/") == 1 and line[:2].isdigit()
        if pending or starts_row:
            if starts_row and pending:
                pending.clear()
            pending.append(line)
            joined = " ".join(pending)
            hit = ROW.match(joined)
            if hit:
                yield hit
                pending.clear()
            elif len(pending) > 6:            # runaway guard
                pending.clear()


def _find(lines: list[tuple[int, str]], *needles: str, after: int = 0) -> int:
    """Index of the first line starting with any of ``needles``, at or after
    ``after``. Prefix, not equality: a "Total ..." label shares its line with
    the amount it introduces ("Total checks $553.69"), not a line of its own.
    """
    for i in range(after, len(lines)):
        if any(lines[i][1].startswith(n) for n in needles):
            return i
    return -1


def parse(path: str) -> Statement:
    page_texts = pages(path)
    lines = list(numbered_lines(page_texts))
    blob = "\n".join(t for _, t in lines)

    m = STATEMENT_DATE.search(blob)
    if not m:
        raise ValueError(f"{os.path.basename(path)}: no statement date found")
    close = datetime.strptime(m.group(1), "%B %d, %Y").date()

    acct = ACCOUNT.search(blob)
    last4 = re.sub(r"\D", "", acct.group(1))[-4:] if acct else "????"

    balances = BALANCE_ON.findall(blob)
    if len(balances) < 2:
        raise ValueError(f"{os.path.basename(path)}: opening/closing balance not found")
    (om, od, obal), (_, _, cbal) = balances[0], balances[-1]
    start = _year_for(int(om), int(od), close)

    stmt = Statement(
        account="checking", account_last4=last4, path=path,
        close_date=close, period_start=start, period_end=close,
    )
    stmt.summary["beginning_balance"] = money(obal)
    stmt.summary["ending_balance"] = money(cbal)

    for pat, key in ((TOTAL_CHECKS, "checks"), (TOTAL_OTHER_WITHDRAWALS, "other_withdrawals"),
                     (TOTAL_WITHDRAWALS, "withdrawals"), (TOTAL_DEPOSITS, "deposits")):
        hit = pat.search(blob)
        if hit:
            stmt.summary[key] = money(hit.group(1))

    # Anchors are found strictly in document order, each searched only after
    # the previous one ends. "Deposits and interest" as a bare label would
    # otherwise prefix-match the *earlier* "Deposits and interest 1,291.34"
    # line in the Activity Summary block, which names the same words but isn't
    # the section header -- anchoring on "Activity detail" first rules that
    # line out entirely.
    detail = _find(lines, "Activity detail")
    deposits_start = _find(lines, "Deposits and interest", after=max(detail, 0))
    deposits_end = _find(lines, "Total deposits and interest", after=max(deposits_start, 0))
    checks_start = _find(lines, "Checks", after=max(deposits_end, 0))
    checks_end = _find(lines, "Total checks", after=max(checks_start, 0))
    other_start = _find(lines, "Other withdrawals", after=max(checks_end, 0))
    other_end = _find(lines, "Total other withdrawals", after=max(other_start, 0))

    # --- checks: two (number, date, amount) columns per line -----------------
    if checks_start >= 0 and checks_end > checks_start:
        for lineno, line in lines[checks_start:checks_end]:
            for num, mm, dd, amt in CHECK_PAIR.findall(line):
                stmt.txns.append(Txn(
                    account="checking", account_last4=last4,
                    date=_year_for(int(mm), int(dd), close),
                    description=f"Check {num}", amount=-money(amt), kind="withdrawal",
                    statement_close=close, period_start=start, period_end=close,
                    source_file=os.path.basename(path), source_line=lineno,
                ))

    # --- other withdrawals and deposits: wrapping rows ------------------------
    for section_start, section_end, sign, kind in (
        (deposits_start, deposits_end, 1, "deposit"),
        (other_start, other_end, -1, "withdrawal"),
    ):
        if section_start < 0 or section_end <= section_start:
            continue
        for hit in _rows_between(lines, section_start, section_end):
            mm, dd, desc, amt = hit.groups()
            lineno = lines[section_start][0]
            stmt.txns.append(Txn(
                account="checking", account_last4=last4,
                date=_year_for(int(mm), int(dd), close),
                description=" ".join(desc.split()), amount=sign * money(amt), kind=kind,
                statement_close=close, period_start=start, period_end=close,
                source_file=os.path.basename(path), source_line=lineno,
            ))

    _validate(stmt)
    return stmt


def _validate(stmt: Statement) -> None:
    checks_total = round(-sum(t.amount for t in stmt.txns if t.description.startswith("Check ")), 2)
    other_total = round(-sum(t.amount for t in stmt.txns
                              if t.kind == "withdrawal" and not t.description.startswith("Check ")), 2)
    deposits_total = round(sum(t.amount for t in stmt.txns if t.kind == "deposit"), 2)

    if "checks" in stmt.summary:
        stmt.checks.append(Check("checks_total", stmt.summary["checks"], checks_total))
    if "other_withdrawals" in stmt.summary:
        stmt.checks.append(Check("other_withdrawals_total", stmt.summary["other_withdrawals"], other_total))
    if "withdrawals" in stmt.summary:
        stmt.checks.append(
            Check("withdrawals_total", stmt.summary["withdrawals"], round(checks_total + other_total, 2))
        )
    if "deposits" in stmt.summary:
        stmt.checks.append(Check("deposits_total", stmt.summary["deposits"], deposits_total))

    begin, end_bal = stmt.summary.get("beginning_balance"), stmt.summary.get("ending_balance")
    if begin is not None and end_bal is not None:
        stmt.checks.append(
            Check("ending_balance", end_bal, round(begin + sum(t.amount for t in stmt.txns), 2))
        )
