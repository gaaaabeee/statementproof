"""CLI: parse every statement, validate it, and write the tables.

    python -m statement_reconciler.run              # parse + report + write out/
    python -m statement_reconciler.run --report     # report only, write nothing
    python -m statement_reconciler.run --strict     # non-zero exit if any check fails

Nothing is written unless every statement passes its own checks, unless you
pass --force. Silent bad data is worse than no data.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from datetime import date

from . import formats
from .records import TXN_FIELDS, Statement, normalize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATEMENTS = os.path.join(ROOT, "statements")
OUT = os.path.join(ROOT, "out")

# Categories that are never outgoing spending.
NON_SPEND = {"Transfers", "Refunds", "Income", "Reimbursements", "One-off deposits"}


def find_pdfs(root: str) -> list:
    """Every PDF under a folder, recursively, in a stable order."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        out += [os.path.join(dirpath, f) for f in filenames
                if f.lower().endswith(".pdf") and not f.startswith(".")]
    return sorted(out)


def discover(root: str) -> tuple:
    """Identify every PDF under ``root``.

    Returns (matched, unmatched) detections. Folder layout is irrelevant --
    each file is identified from its own first page -- so this can be pointed
    at whatever directory the downloads landed in.
    """
    detections = [formats.detect(p) for p in find_pdfs(root)]
    return [d for d in detections if d.ok], [d for d in detections if not d.ok]


def parse_all(root: str = STATEMENTS) -> tuple:
    matched, unmatched = discover(root)
    return [d.format.parse(d.path) for d in matched], matched, unmatched


def accounts(stmts: list) -> dict:
    """Group statements by the real-world account they belong to."""
    groups = {}
    for s in stmts:
        groups.setdefault(s.key, []).append(s)
    for seq in groups.values():
        seq.sort(key=lambda s: s.period_start)
    return groups


def label(key: tuple) -> str:
    account, last4 = key
    return f"{account} ···{last4}"


def continuity(stmts: list) -> list:
    """Cross-statement checks, for any number of accounts of any kind.

    Each account is checked independently for coverage gaps and a balance
    chain, then all of them together against the net of every parsed row.
    """
    problems = []
    groups = accounts(stmts)

    for key, seq in sorted(groups.items()):
        for prev, cur in zip(seq, seq[1:]):
            gap = (cur.period_start - prev.period_end).days
            if gap != 1:
                problems.append(
                    f"{label(key)}: {prev.period_end} -> {cur.period_start} "
                    f"is a {gap - 1:+d} day gap/overlap ({os.path.basename(cur.path)})"
                )
            a, b = prev.closing_balance, cur.opening_balance
            if a is not None and b is not None and abs(a - b) > 0.005:
                problems.append(
                    f"{label(key)}: balance chain breaks at {os.path.basename(cur.path)}: "
                    f"prior close {a:,.2f} != open {b:,.2f}"
                )

    # Whole-corpus check: the net of every signed amount ever parsed must equal
    # the change in position across every account, each weighted by whether it
    # is an asset or a debt. This ties every row to two numbers per account and
    # only balances if the sign convention is right and no row is missing or
    # duplicated.
    expected, parts, complete = 0.0, [], True
    for key, seq in sorted(groups.items()):
        fmt = formats.BY_ACCOUNT_KIND.get(key[0])
        open_bal, close_bal = seq[0].opening_balance, seq[-1].closing_balance
        if fmt is None or open_bal is None or close_bal is None:
            complete = False
            continue
        delta = close_bal - open_bal
        expected += fmt.polarity * delta
        parts.append(f"{label(key)} {delta:+,.2f}")

    if complete and parts:
        actual = round(sum(t.signed for s in stmts for t in s.txns), 2)
        if abs(round(expected, 2) - actual) > 0.01:
            problems.append(
                f"net position: parsed rows net {actual:,.2f} but balances moved "
                f"{expected:,.2f} ({', '.join(parts)})"
            )
    return problems


def report(stmts: list[Statement]) -> tuple[int, int]:
    failures = unparsed = 0
    print(f"{'statement':32} {'period':25} {'rows':>5}  checks")
    print("-" * 96)
    for s in sorted(stmts, key=lambda s: (s.account, s.period_start)):
        bad = [c for c in s.checks if not c.ok]
        status = "OK" if not bad else "FAIL " + ", ".join(
            f"{c.name}(Δ{c.delta:+,.2f})" for c in bad
        )
        print(
            f"{os.path.basename(s.path):32} "
            f"{s.period_start}..{s.period_end} {len(s.txns):>5}  {status}"
        )
        failures += len(bad)
        for lineno, text in s.unparsed:
            unparsed += 1
            print(f"    ! unparsed line {lineno}: {text[:88]}")
    return failures, unparsed


def spend_rows(stmts: list[Statement]) -> list:
    """Transactions that represent actual outgoing spending.

    Card purchases and cash advances, plus checking withdrawals that are not
    transfers (a card payment out of checking is the same money as the card
    purchases it settles, so counting both would double-count).
    """
    out = []
    for s in stmts:
        for t in s.txns:
            _, category = normalize(t.description, t.account, t.kind)
            if category in NON_SPEND:
                continue
            if t.account == "credit" and t.kind in ("purchase", "cash_advance", "fee", "interest"):
                out.append(t)
            elif t.account == "checking" and t.kind == "withdrawal":
                out.append(t)
    return out


def categorize_report(stmts: list[Statement], show_uncategorized: bool) -> None:
    rows = spend_rows(stmts)
    total = sum(-t.signed for t in rows)
    by_cat = {}
    for t in rows:
        _, cat = normalize(t.description, t.account, t.kind)
        by_cat[cat] = by_cat.get(cat, 0.0) + -t.signed

    print("\nspending by category (excludes transfers, refunds, income)")
    print("-" * 56)
    for cat, amt in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:24} {amt:>12,.2f}  {amt / total * 100:>5.1f}%")
    print(f"  {'TOTAL':24} {total:>12,.2f}")

    unc = [t for t in rows if normalize(t.description, t.account, t.kind)[1] == "uncategorized"]
    unc_amt = sum(-t.signed for t in unc)
    print(
        f"\ncategorized: {(1 - unc_amt / total) * 100:.1f}% of spend "
        f"({len(rows) - len(unc):,}/{len(rows):,} rows); "
        f"{unc_amt:,.2f} across {len(unc):,} rows still uncategorized"
    )

    if show_uncategorized and unc:
        merch = {}
        for t in unc:
            m = normalize(t.description, t.account, t.kind)[0]
            hit = merch.setdefault(m, [0, 0.0])
            hit[0] += 1
            hit[1] += -t.signed
        from .config import config_path
        print(f"\nuncategorized merchants, worst by spend "
              f"(add rules in {config_path()}):")
        for m, (n, amt) in sorted(merch.items(), key=lambda kv: -kv[1][1])[:40]:
            print(f"  {amt:>10,.2f}  x{n:<4} {m[:60]}")


def write_tables(stmts: list[Statement]) -> None:
    os.makedirs(OUT, exist_ok=True)

    txn_path = os.path.join(OUT, "transactions.csv")
    rows = [t for s in stmts for t in s.txns]
    rows.sort(key=lambda t: (t.date, t.account, t.source_file, t.source_line))
    with open(txn_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TXN_FIELDS)
        w.writeheader()
        for t in rows:
            w.writerow(t.as_row())

    stmt_path = os.path.join(OUT, "statements.csv")
    keys = sorted({k for s in stmts for k in s.summary})
    with open(stmt_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["account", "account_last4", "file", "period_start", "period_end",
                    "txn_count", "checks_passed"] + keys)
        for s in sorted(stmts, key=lambda s: (s.account, s.period_start)):
            w.writerow(
                [s.account, s.account_last4, os.path.basename(s.path),
                 s.period_start, s.period_end, len(s.txns), s.ok]
                + [s.summary.get(k, "") for k in keys]
            )

    # Month x category spending matrix, ready for a chart.
    spend = spend_rows(stmts)
    months = sorted({t.date.strftime("%Y-%m") for t in spend})
    cats = sorted({normalize(t.description, t.account, t.kind)[1] for t in spend})
    grid = {(m, c): 0.0 for m in months for c in cats}
    for t in spend:
        key = (t.date.strftime("%Y-%m"), normalize(t.description, t.account, t.kind)[1])
        grid[key] += -t.signed

    cat_path = os.path.join(OUT, "by_category.csv")
    with open(cat_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month"] + cats + ["total"])
        for m in months:
            vals = [round(grid[(m, c)], 2) for c in cats]
            w.writerow([m] + vals + [round(sum(vals), 2)])

    print(f"\nwrote {len(rows):,} transactions -> {os.path.relpath(txn_path, ROOT)}")
    print(f"wrote {len(stmts)} statements   -> {os.path.relpath(stmt_path, ROOT)}")
    print(f"wrote {len(months)} months x {len(cats)} categories -> {os.path.relpath(cat_path, ROOT)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true", help="validate only, write nothing")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on any failure")
    ap.add_argument("--force", action="store_true", help="write tables even if checks fail")
    ap.add_argument("--uncategorized", action="store_true",
                    help="list merchants with no category, worst by spend")
    ap.add_argument("--folder", metavar="DIR", default=STATEMENTS,
                    help="folder of statement PDFs (searched recursively)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.folder):
        print(f"not a folder: {args.folder}", file=sys.stderr)
        return 2

    stmts, matched, unmatched = parse_all(args.folder)

    if unmatched:
        print(f"{len(unmatched)} file(s) could not be identified:")
        for d in unmatched:
            print(f"  ! {d.describe()}")
        print()
    if not stmts:
        print(f"no supported statements found under {args.folder}", file=sys.stderr)
        return 2

    by_format = {}
    for d in matched:
        by_format[d.format.label] = by_format.get(d.format.label, 0) + 1
    print("detected: " + ", ".join(f"{n} x {lbl}" for lbl, n in sorted(by_format.items())))

    failures, unparsed = report(stmts)
    problems = continuity(stmts)

    print()
    groups = accounts(stmts)
    print(f"accounts: {len(groups)} — "
          + ", ".join(f"{label(k)} ({len(v)} statements)" for k, v in sorted(groups.items())))
    if problems:
        print("cross-statement problems:")
        for p in problems:
            print(f"  ! {p}")
    else:
        print("cross-statement: coverage contiguous, balances chain cleanly")

    total_rows = sum(len(s.txns) for s in stmts)
    print(
        f"summary: {len(stmts)} statements, {total_rows:,} transactions, "
        f"{failures} failed checks, {unparsed} unparsed lines, {len(problems)} continuity problems"
    )

    categorize_report(stmts, args.uncategorized)

    clean = not failures and not problems and not unparsed
    if not args.report:
        if clean or args.force:
            write_tables(stmts)
        else:
            print("\nrefusing to write tables while checks fail (use --force to override)")

    return 1 if (args.strict and not clean) else 0


if __name__ == "__main__":
    raise SystemExit(main())
