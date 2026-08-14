"""Parser for Chase personal checking statements.

Layout: a single TRANSACTION DETAIL table, possibly continued across pages,
with columns ``DATE DESCRIPTION AMOUNT BALANCE``. The running balance column
is the thing that makes this parser trustworthy -- see ``_validate``.

Verified against Chase Total Checking statements, 2024-2026. Other Chase
checking products may differ; the validation in ``_validate`` is what stops a
layout mismatch from silently producing wrong numbers.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from .records import Check, Statement, Txn
from .text import MONEY, money, numbered_lines, pages, resolve_year

PERIOD = re.compile(
    r"([A-Z][a-z]+ \d{1,2}, \d{4})\s*through\s*([A-Z][a-z]+ \d{1,2}, \d{4})"
)
ACCOUNT = re.compile(r"Account Number:\s*(\d+)")
TABLE_HEADER = re.compile(r"^DATE DESCRIPTION AMOUNT BALANCE$")
BEGIN_BAL = re.compile(rf"^Beginning Balance \$?({MONEY})$")
END_BAL = re.compile(rf"^Ending Balance \$?({MONEY})$")
ROW = re.compile(rf"^(\d{{2}})/(\d{{2}}) (.+?) ({MONEY}) ({MONEY})$")

# Summary buckets on page 1. Every withdrawal bucket prints negative.
SUMMARY_ROWS = {
    "deposits": re.compile(rf"^Deposits and Additions ({MONEY})$"),
    "card_withdrawals": re.compile(rf"^ATM & Debit Card Withdrawals ({MONEY})$"),
    "electronic_withdrawals": re.compile(rf"^Electronic Withdrawals ({MONEY})$"),
    "other_withdrawals": re.compile(rf"^Other Withdrawals ({MONEY})$"),
    "checks_paid": re.compile(rf"^Checks Paid ({MONEY})$"),
    "fees": re.compile(rf"^Fees ({MONEY})$"),
}

# Lines inside the table that are structural, not transactions.
TABLE_NOISE = re.compile(
    r"^(TRANSACTION DETAIL|DATE DESCRIPTION|\*(start|end)\*|Page \d|"
    r"\d+ \d+Page of|Account Number:|[A-Z][a-z]+ \d{1,2}, \d{4} through)"
)


def classify(description: str, amount: float) -> str:
    return "deposit" if amount > 0 else "withdrawal"


def parse(path: str) -> Statement:
    page_texts = pages(path)
    lines = list(numbered_lines(page_texts))
    blob = "\n".join(t for _, t in lines)

    m = PERIOD.search(blob)
    if not m:
        raise ValueError(f"{os.path.basename(path)}: no statement period found")
    start = datetime.strptime(m.group(1), "%B %d, %Y").date()
    end = datetime.strptime(m.group(2), "%B %d, %Y").date()

    acct = ACCOUNT.search(blob)
    last4 = acct.group(1)[-4:] if acct else "????"

    stmt = Statement(
        account="checking",
        account_last4=last4,
        path=path,
        close_date=end,
        period_start=start,
        period_end=end,
    )

    # --- summary block (first occurrence wins; the table repeats some labels)
    for key, pat in SUMMARY_ROWS.items():
        for _, line in lines:
            hit = pat.match(line)
            if hit:
                stmt.summary[key] = money(hit.group(1))
                break

    # --- transaction table
    #
    # A long description wraps onto up to a few extra lines, with the amount
    # and balance landing on the last one, e.g.
    #
    #   06/12 06/12 Online Domestic Wire Transfer Via: Some Bank Na/065000000
    #   A/C: Recipient Name City ST 00000 US Ref: Payment Reference -
    #   Sender Name Imad: 0000Xxxxxxx000000 Trn: 0000000000Es
    #   -9,500.00 321.89
    #
    # so a row that doesn't match on its own is buffered and re-tested as each
    # following line is appended. (pypdf's layout mode keeps such rows on one
    # line but runs the description into the amount -- "Card 0000-5.63682.48"
    # -- so joining the default extraction is the safer of the two.)
    in_table = False
    pending: list[tuple[int, str]] = []

    def drop_pending() -> None:
        stmt.unparsed.extend(pending)
        pending.clear()

    def emit(lineno: int, hit: re.Match) -> None:
        mm, dd, desc, amt, bal = hit.groups()
        value = money(amt)
        stmt.txns.append(
            Txn(
                account="checking",
                account_last4=last4,
                date=resolve_year(int(mm), int(dd), start, end),
                description=" ".join(desc.split()),
                amount=value,
                kind=classify(desc, value),
                balance=money(bal),
                statement_close=end,
                period_start=start,
                period_end=end,
                source_file=os.path.basename(path),
                source_line=lineno,
            )
        )

    for lineno, line in lines:
        if TABLE_HEADER.match(line):
            drop_pending()
            in_table = True
            continue
        if not in_table:
            hit = BEGIN_BAL.match(line)
            if hit and "beginning_balance" not in stmt.summary:
                stmt.summary["beginning_balance"] = money(hit.group(1))
            continue

        hit = END_BAL.match(line)
        if hit:
            drop_pending()
            stmt.summary.setdefault("ending_balance", money(hit.group(1)))
            in_table = False
            continue

        hit = BEGIN_BAL.match(line)
        if hit:
            stmt.summary.setdefault("beginning_balance", money(hit.group(1)))
            continue

        # A self-contained row always wins; anything still buffered was never
        # completed, so surface it rather than letting it corrupt this row.
        hit = ROW.match(line)
        if hit:
            drop_pending()
            emit(lineno, hit)
            continue

        starts_row = line[:6].count("/") == 1 and line[:2].isdigit()
        if pending or starts_row:
            if starts_row and pending:
                drop_pending()
            pending.append((lineno, line))
            joined = " ".join(t for _, t in pending)
            hit = ROW.match(joined)
            if hit:
                emit(pending[0][0], hit)
                pending.clear()
            elif len(pending) > 6:      # runaway guard
                drop_pending()
            continue

        if not TABLE_NOISE.match(line):
            stmt.unparsed.append((lineno, line))

    drop_pending()

    _validate(stmt)
    return stmt


def _validate(stmt: Statement) -> None:
    """Check parsed rows against the numbers the statement prints itself."""
    begin = stmt.summary.get("beginning_balance")
    end_bal = stmt.summary.get("ending_balance")

    # 1. Running balance: walking every parsed amount forward from the opening
    #    balance must reproduce each printed balance exactly. A dropped row, a
    #    duplicated row, or a misread amount all break this.
    if begin is not None:
        running = begin
        breaks = 0
        for t in stmt.txns:
            running = round(running + t.amount, 2)
            if t.balance is not None and abs(running - t.balance) > 0.005:
                breaks += 1
                running = t.balance      # resync so one error isn't N errors
        stmt.checks.append(Check("running_balance_breaks", 0, breaks, tolerance=0))

    # 2. Opening + net of all rows == printed closing balance.
    if begin is not None and end_bal is not None:
        stmt.checks.append(
            Check("ending_balance", end_bal, round(begin + sum(t.amount for t in stmt.txns), 2))
        )

    # 3. Summary buckets: deposits and total withdrawals, independently.
    if "deposits" in stmt.summary:
        stmt.checks.append(
            Check("deposits_total", stmt.summary["deposits"],
                  round(sum(t.amount for t in stmt.txns if t.amount > 0), 2))
        )
    wd_keys = ("card_withdrawals", "electronic_withdrawals", "other_withdrawals",
               "checks_paid", "fees")
    if any(k in stmt.summary for k in wd_keys):
        expected = round(sum(stmt.summary.get(k, 0.0) for k in wd_keys), 2)
        stmt.checks.append(
            Check("withdrawals_total", expected,
                  round(sum(t.amount for t in stmt.txns if t.amount < 0), 2))
        )
