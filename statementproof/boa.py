"""Parser for Bank of America personal checking statements.

Layout differs from Chase in three ways that shape this parser:

1. **Layout-mode extraction is mandatory.** The default text layer runs every
   field together without delimiters -- a whole transaction table arrives as one
   unbroken string -- so the column positions are the only thing separating a
   description from its amount.
2. **There is no running balance column.** Chase checking can be proved row by
   row; here the proof comes from the per-section totals the statement prints
   ("Total ATM and debit card subtractions -$3,474.03") plus the opening and
   closing balances. That is still four to six independent checks per statement.
3. **Descriptions wrap *after* the amount**, not before it. A row is complete on
   its first line and the overflow lands underneath, which is the opposite of
   Chase's wrapped rows.

Amounts print with their sign already attached (deposits positive, subtractions
negative), so the sign is read rather than inferred from the section.
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from datetime import datetime

from pypdf import PdfReader

from .records import Check, Statement, Txn

MONEY = r"-?\$?-?[\d,]+\.\d{2}"

PERIOD = re.compile(
    r"^for ([A-Z][a-z]+ \d{1,2}, \d{4}) to ([A-Z][a-z]+ \d{1,2}, \d{4})", re.M
)
ACCOUNT = re.compile(r"Account number:\s*([\d ]{4,})")
PRODUCT = re.compile(r"^Your ([A-Z].+?)\s*$", re.M)
ROW = re.compile(rf"^(\d{{2}})/(\d{{2}})/(\d{{2}})\s+(.+?)\s+({MONEY})$")

BEGIN_BAL = re.compile(rf"^Beginning balance on [A-Z][a-z]+ \d{{1,2}}, \d{{4}}\s+({MONEY})$")
END_BAL = re.compile(rf"^Ending balance on [A-Z][a-z]+ \d{{1,2}}, \d{{4}}\s+({MONEY})$")

# Section name -> the summary key it reconciles against. "Withdrawals and other
# subtractions" is only a banner over the subsections, never a row container.
SECTIONS = {
    "Deposits and other additions": "deposits",
    "ATM and debit card subtractions": "atm_debit",
    "Other subtractions": "other_subtractions",
    "Checks": "checks",
    "Service fees": "service_fees",
}
BANNER = "Withdrawals and other subtractions"

SECTION_HEADER = re.compile(
    r"^(" + "|".join(re.escape(s) for s in SECTIONS) + r"|" + re.escape(BANNER) + r")"
    r"(?: - continued)?$"
)
SECTION_TOTAL = re.compile(
    r"^Total (" + "|".join(re.escape(s.lower()) for s in SECTIONS) + r")\s+(" + MONEY + r")$",
    re.I,
)
# Summary lines look like a section header with a trailing amount.
SUMMARY_ROW = re.compile(
    r"^(" + "|".join(re.escape(s) for s in SECTIONS) + r")\s+(" + MONEY + r")$"
)

# Structural furniture that appears inside a section but is not data.
NOISE = re.compile(
    r"^(Date\b.{0,40}\bAmount|continued on the next page|Page \d+ of \d+|"
    r".+ ! Account # [\d ]+ ! .+|Total .+)$"
)
# A wrapped fragment stays on one line; the longest seen is an international
# wire's originator block at 78 characters. Marketing copy inside a section
# would exceed this, and anything that does is reported rather than absorbed.
MAX_CONTINUATION = 100


def money(s: str) -> float:
    s = s.strip().replace(",", "").replace("$", "").replace(" ", "")
    neg = s.startswith("-")
    s = s.lstrip("-+")
    if s.startswith("."):
        s = "0" + s
    val = float(s)
    return -val if neg else val


def layout_pages(path: str) -> list:
    """Page text in layout mode, whitespace-collapsed per line."""
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        for page in PdfReader(path).pages:
            text = page.extract_text(extraction_mode="layout") or ""
            out.append([re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.split("\n")])
    return out


def classify(amount: float) -> str:
    return "deposit" if amount > 0 else "withdrawal"


# --- descriptor envelope ----------------------------------------------------
# BoA wraps the merchant in the channel that produced the transaction, plus a
# 23-digit network reference. Stripping that here rather than in the shared
# categorizer is deliberate: the wrapper is this bank's formatting, and a
# generic cleanup that tried to handle every bank's wrapper over-stripped --
# "CHECKCARD 0402 UNITED 8009322732 TX 5543..." collapsed to "Checkcard 0402",
# eating the airline entirely.

# "VICTORIA'S SEC 06/22 #000035420 MOBILE PURCHASE VICTORIA'S SECR HOUSTON TX"
# prints the merchant twice, truncated to different widths. Usually the second
# copy is the fuller one -- but not always: sometimes it is the street address,
# and taking it blindly loses the brand outright
# ("IKEA HOUSTON ... 7810 KATY FREEWAY" became "7810 Katy Freeway").
BOA_DOUBLED = re.compile(
    r"^(?P<first>.{2,}?)\s+\d{2}/\d{2}\s+(?:#\d+\s+)?"
    r"(?:MOBILE\s+|RECURRING\s+)?(?:PURCHASE|WITHDRWL|WITHDRAWAL|REFUND|DEPOSIT)\s+"
    r"(?P<second>\S.*)$",
    re.I,
)
# A second copy starting with a digit is an address or a store code rather
# than a name ("7810 KATY FREEWAY", "02988--4715 Westh"), so the first copy --
# which carries the brand -- is the better one.
BOA_STREET = re.compile(r"^\d")
BOA_CHANNEL = re.compile(
    r"^(?:RECURRING\s+)?(?:CHECKCARD|CHECK CARD|PURCHASE|MOBILE PURCHASE|"
    r"ATM WITHDRAWAL|ATM CASH WITHDRAWAL|WITHDRWL|PRE-AUTH|POS)\s+\d{4}\s+",
    re.I,
)
BOA_AUTH = re.compile(r"\s+\d{15,}\s*$")


def strip_envelope(text: str) -> str:
    """Remove BoA's channel wrapper, leaving the merchant portion."""
    hit = BOA_DOUBLED.match(text)
    if hit:
        first, second = hit.group("first").strip(), hit.group("second").strip()
        text = first if BOA_STREET.match(second) else second
    text = BOA_CHANNEL.sub("", text)
    text = BOA_AUTH.sub("", text)
    return text.strip()


def parse(path: str) -> Statement:
    pages = layout_pages(path)
    flat = [(n, ln) for n, page in enumerate(pages) for ln in page if ln]

    blob = "\n".join(ln for _, ln in flat)
    m = PERIOD.search(blob)
    if not m:
        raise ValueError(f"{os.path.basename(path)}: no statement period found")
    start = datetime.strptime(m.group(1), "%B %d, %Y").date()
    end = datetime.strptime(m.group(2), "%B %d, %Y").date()

    acct = ACCOUNT.search(blob)
    last4 = acct.group(1).replace(" ", "")[-4:] if acct else "????"

    stmt = Statement(
        account="checking",
        account_last4=last4,
        path=path,
        close_date=end,
        period_start=start,
        period_end=end,
    )

    prod = PRODUCT.search(blob)
    if prod and "Account" not in prod.group(1):
        stmt.summary["product"] = prod.group(1)

    section = None
    last_txn = None
    lineno = 0

    for _, line in flat:
        lineno += 1

        hit = BEGIN_BAL.match(line)
        if hit:
            stmt.summary.setdefault("beginning_balance", money(hit.group(1)))
            continue
        hit = END_BAL.match(line)
        if hit:
            stmt.summary.setdefault("ending_balance", money(hit.group(1)))
            continue

        # Summary block: same words as a section header, but with an amount.
        hit = SUMMARY_ROW.match(line)
        if hit:
            stmt.summary.setdefault(SECTIONS[hit.group(1)], money(hit.group(2)))
            continue

        hit = SECTION_TOTAL.match(line)
        if hit:
            name = next(s for s in SECTIONS if s.lower() == hit.group(1).lower())
            stmt.summary.setdefault(f"total_{SECTIONS[name]}", money(hit.group(2)))
            section = None
            last_txn = None
            continue

        hit = SECTION_HEADER.match(line)
        if hit:
            # The banner is not a row container; only its subsections are.
            section = None if hit.group(1) == BANNER else hit.group(1)
            last_txn = None
            continue

        if line.startswith("continued on the next page"):
            section = None
            last_txn = None
            continue

        if section is None:
            continue

        hit = ROW.match(line)
        if hit:
            mm, dd, yy, desc, amt = hit.groups()
            value = money(amt)
            last_txn = Txn(
                account="checking",
                account_last4=last4,
                date=datetime.strptime(f"{mm}/{dd}/{yy}", "%m/%d/%y").date(),
                description=" ".join(desc.split()),
                amount=value,
                kind=classify(value),
                statement_close=end,
                period_start=start,
                period_end=end,
                source_file=os.path.basename(path),
                source_line=lineno,
            )
            stmt.txns.append(last_txn)
            continue

        if NOISE.match(line):
            continue

        # A short orphan line inside a section is the tail of the description
        # above it, which wrapped after its amount ("...CO ID:9876543210" / "WEB").
        if last_txn is not None and len(line) <= MAX_CONTINUATION:
            last_txn.description = f"{last_txn.description} {line}".strip()
            continue

        stmt.unparsed.append((lineno, line))

    # Set after the loop so wrapped continuations are already appended.
    for t in stmt.txns:
        t.descriptor = strip_envelope(t.description)

    _validate(stmt)
    return stmt


def _validate(stmt: Statement) -> None:
    """Reconcile parsed rows against the totals the statement prints."""
    s = stmt.summary
    deposits = round(sum(t.amount for t in stmt.txns if t.amount > 0), 2)
    subtractions = round(sum(t.amount for t in stmt.txns if t.amount < 0), 2)

    # 1. Each printed section total must equal the rows parsed under it. The
    #    per-section totals are the only row-level proof this format offers.
    if "total_deposits" in s:
        stmt.checks.append(Check("deposits_total", s["total_deposits"], deposits))
    printed_subs = [k for k in ("total_atm_debit", "total_other_subtractions",
                                "total_checks", "total_service_fees") if k in s]
    if printed_subs:
        stmt.checks.append(
            Check("subtractions_total", round(sum(s[k] for k in printed_subs), 2), subtractions)
        )

    # 2. The page-1 summary must agree with the section totals it summarises.
    for key, total_key in (("deposits", "total_deposits"),
                           ("atm_debit", "total_atm_debit"),
                           ("other_subtractions", "total_other_subtractions"),
                           ("checks", "total_checks"),
                           ("service_fees", "total_service_fees")):
        if key in s and total_key in s:
            stmt.checks.append(Check(f"summary_agrees_{key}", s[key], s[total_key]))

    # 3. Opening plus everything parsed must land on the printed closing
    #    balance. This one holds even for a statement with no activity at all.
    if "beginning_balance" in s and "ending_balance" in s:
        stmt.checks.append(
            Check("ending_balance", s["ending_balance"],
                  round(s["beginning_balance"] + deposits + subtractions, 2))
        )
