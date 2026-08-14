"""Parser for Chase consumer credit card statements.

Layout: an ACCOUNT ACTIVITY list of ``MM/DD DESCRIPTION AMOUNT`` rows spread
over several pages. There is no running balance, but page 1 prints a summary
(previous balance, payments, purchases, fees, interest, new balance) that the
parsed rows must add up to -- that is the checksum this parser leans on.

Note on sections: the PDF's text layer emits the section headers (PAYMENTS AND
OTHER CREDITS / PURCHASE / FEES CHARGED) *after* the rows they head, so row
classification is driven by sign and description rather than by position.

Verified against Sapphire-family statements, 2024-2026. Other Chase card
products may differ; ``_validate`` is what stops a mismatch from silently
producing wrong numbers.
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from datetime import datetime

from pypdf import PdfReader

from .records import Check, Statement, Txn
from .text import money, numbered_lines, pages, resolve_year

# Summary values print with a leading sign outside the '$' ("-$1,234.56",
# "+$1,234.56"), which is why this is looser than text.MONEY.
SUM = r"[-+]?\$?-?[\d,]+\.\d{2}"

PERIOD = re.compile(r"Opening/Closing Date (\d{2}/\d{2}/\d{2}) ?- ?(\d{2}/\d{2}/\d{2})")
ACCOUNT = re.compile(r"Account [Nn]umber:\s*(?:X+ ?)*(\d{4})")
ROW = re.compile(r"^(\d{2})/(\d{2}) (.+?) (-?\$?-?[\d,]*\.\d{2})$")

SUMMARY_ROWS = {
    "previous_balance": re.compile(rf"^Previous Balance ({SUM})$"),
    "payments_credits": re.compile(rf"^Payment,? Credits ({SUM})$"),
    "purchases": re.compile(rf"^Purchases ({SUM})$"),
    "cash_advances": re.compile(rf"^Cash Advances ({SUM})$"),
    "balance_transfers": re.compile(rf"^Balance Transfers ({SUM})$"),
    "fees_charged": re.compile(rf"^Fees Charged ({SUM})$"),
    "interest_charged": re.compile(rf"^Interest Charged ({SUM})$"),
    "new_balance": re.compile(rf"^New Balance ({SUM})$"),
}
TOTAL_FEES = re.compile(rf"^TOTAL FEES FOR THIS PERIOD \$?({SUM})$")
TOTAL_INTEREST = re.compile(rf"^TOTAL INTEREST FOR THIS PERIOD \$?({SUM})$")

FEE_WORDS = re.compile(
    r"\b(TRANSACTION FEE|ANNUAL MEMBERSHIP FEE|MEMBERSHIP FEE|LATE FEE|"
    r"RETURNED PAYMENT FEE|OVERLIMIT FEE|FOREIGN TRANSACTION FEE)\b",
    re.I,
)
INTEREST_WORDS = re.compile(r"INTEREST CHARGE", re.I)
PAYMENT_WORDS = re.compile(r"\bPAYMENT\b", re.I)

# Lines that begin with MM/DD but are not transactions.
ROW_NOISE = re.compile(r"^\d{2}/\d{2}\s*$")

# Section headers, as they read in the printed statement.
SECTION_HEADERS = {
    "PAYMENTS AND OTHER CREDITS": "payment",
    "PURCHASE": "purchase",
    "PURCHASES": "purchase",
    "CASH ADVANCES": "cash_advance",
    "FEES CHARGED": "fee",
    "INTEREST CHARGED": "interest",
}
# Once the APR table starts, "CASH ADVANCES" reappears as a rate row and must
# not be read as a section header.
SECTION_STOP = re.compile(r"^(Annual Percentage Rate|Balance Type|INTEREST CHARGES)")


def section_map(path: str) -> dict[tuple[str, float], str]:
    """Map (MM/DD, amount) -> section, read from a layout-preserving pass.

    The default text layer emits each page's section headers *after* the rows
    they head, so sections can't be inferred from it. Layout mode restores
    reading order; it is used only to label rows (it runs some columns
    together, so the rows themselves are still parsed from the default pass).
    Keys seen under two different sections are dropped as ambiguous.
    """
    out: dict[tuple[str, float], str] = {}
    clashes: set[tuple[str, float]] = set()
    for page in PdfReader(path).pages:
        try:
            # Layout mode warns about rotated text (the statements' vertical
            # margin stamps); irrelevant here and noisy across 40 files.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                logging.getLogger("pypdf").setLevel(logging.ERROR)
                text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            continue
        current = None
        for raw in text.split("\n"):
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue
            if SECTION_STOP.match(line):
                current = None
                continue
            if line in SECTION_HEADERS:
                current = SECTION_HEADERS[line]
                continue
            hit = ROW.match(line)
            if hit and current:
                key = (f"{hit.group(1)}/{hit.group(2)}", money(hit.group(4)))
                if key in out and out[key] != current:
                    clashes.add(key)
                out[key] = current
    for key in clashes:
        out.pop(key, None)
    return out


def classify(description: str, amount: float, section: str | None = None) -> str:
    # Anything negative is a credit no matter what it is called: an interest
    # rebate prints as "PURCHASE INTEREST CHARGE -.23" but Chase books it under
    # Payment/Credits and leaves Interest Charged showing the gross figure.
    if amount < 0:
        return "payment" if PAYMENT_WORDS.search(description) else "credit"
    if section:
        return section
    if INTEREST_WORDS.search(description):
        return "interest"
    if FEE_WORDS.search(description):
        return "fee"
    return "purchase"


def parse(path: str) -> Statement:
    page_texts = pages(path)
    lines = list(numbered_lines(page_texts))
    blob = "\n".join(t for _, t in lines)

    m = PERIOD.search(blob)
    if not m:
        raise ValueError(f"{os.path.basename(path)}: no Opening/Closing Date found")
    start = datetime.strptime(m.group(1), "%m/%d/%y").date()
    end = datetime.strptime(m.group(2), "%m/%d/%y").date()

    acct = ACCOUNT.search(blob)
    last4 = acct.group(1) if acct else "????"
    sections = section_map(path)

    stmt = Statement(
        account="credit",
        account_last4=last4,
        path=path,
        close_date=end,
        period_start=start,
        period_end=end,
    )

    for lineno, line in lines:
        for key, pat in SUMMARY_ROWS.items():
            if key in stmt.summary:
                continue
            hit = pat.match(line)
            if hit:
                stmt.summary[key] = money(hit.group(1))
                break
        else:
            hit = TOTAL_FEES.match(line)
            if hit:
                stmt.summary.setdefault("total_fees_line", money(hit.group(1)))
                continue
            hit = TOTAL_INTEREST.match(line)
            if hit:
                stmt.summary.setdefault("total_interest_line", money(hit.group(1)))
                continue

            hit = ROW.match(line)
            if hit and not ROW_NOISE.match(line):
                mm, dd, desc, amt = hit.groups()
                desc = desc.strip()
                if not desc:
                    continue
                try:
                    when = resolve_year(int(mm), int(dd), start, end)
                except ValueError:
                    stmt.unparsed.append((lineno, line))
                    continue
                value = money(amt)
                stmt.txns.append(
                    Txn(
                        account="credit",
                        account_last4=last4,
                        date=when,
                        description=" ".join(desc.split()),
                        amount=value,
                        kind=classify(desc, value, sections.get((f"{mm}/{dd}", value))),
                        statement_close=end,
                        period_start=start,
                        period_end=end,
                        source_file=os.path.basename(path),
                        source_line=lineno,
                    )
                )

    _validate(stmt)
    return stmt


def _total(stmt: Statement, kind: str) -> float:
    return round(sum(t.amount for t in stmt.txns if t.kind == kind), 2)


def _validate(stmt: Statement) -> None:
    s = stmt.summary

    # Each printed summary bucket must equal the rows classified into it.
    if "purchases" in s:
        stmt.checks.append(Check("purchases_total", s["purchases"], _total(stmt, "purchase")))
    if "payments_credits" in s:
        # Chase's "Payment, Credits" bucket covers card payments, merchant
        # refunds and fee/interest rebates alike.
        stmt.checks.append(
            Check("payments_total", s["payments_credits"],
                  round(_total(stmt, "payment") + _total(stmt, "credit"), 2))
        )
    if "cash_advances" in s:
        stmt.checks.append(
            Check("cash_advances_total", s["cash_advances"], _total(stmt, "cash_advance"))
        )
    if "fees_charged" in s:
        stmt.checks.append(Check("fees_total", s["fees_charged"], _total(stmt, "fee")))
    if "interest_charged" in s:
        stmt.checks.append(
            Check("interest_total", s["interest_charged"], _total(stmt, "interest"))
        )

    # Previous balance plus everything parsed must land on the new balance.
    if "previous_balance" in s and "new_balance" in s:
        stmt.checks.append(
            Check(
                "new_balance",
                s["new_balance"],
                round(s["previous_balance"] + sum(t.amount for t in stmt.txns), 2),
            )
        )

    # The activity pages print their own fee/interest subtotals; make sure
    # those agree with page 1 (catches a page dropped from extraction).
    if "total_fees_line" in s and "fees_charged" in s:
        stmt.checks.append(
            Check("fees_page_agrees", s["fees_charged"], s["total_fees_line"])
        )
    if "total_interest_line" in s and "interest_charged" in s:
        stmt.checks.append(
            Check("interest_page_agrees", s["interest_charged"], s["total_interest_line"])
        )
