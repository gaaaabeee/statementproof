"""Categorization accuracy harness.

    ./.venv/bin/python -m statementproof.eval
    ./.venv/bin/python -m statementproof.eval -v                  # list every miss
    ./.venv/bin/python -m statementproof.eval --min-accuracy 0.9  # exit 1 below this

Reconciliation proves amounts are right against numbers the statement prints
itself; nothing proves categories are right the same way -- a rule either
exists or it doesn't, and a bad regex can silently steal or miss rows. This
gives that a measurable number instead of an impression.

Scores against ``tests/fixtures/eval_set.jsonl``: invented descriptors with an
``expected_merchant``/``expected_category`` computed against the *shipped*
ruleset and hand-reviewed (see ``expected_*`` provenance comment in that file),
not against whatever rules happen to be configured on this machine --
``tests/fixtures/eval_rules.json`` is deliberately empty, so a developer's own
rent or payroll rule never changes the score. Point ``--rules`` elsewhere to
score a different ruleset, e.g. a real config, on demand.

Two numbers matter, and they catch different regressions:

* ``coverage``  -- of rows that should be categorized, how many weren't left
  sitting in ``uncategorized``. Drops when a rule stops matching.
* ``accuracy``  -- of every row, how many got *exactly* the labeled merchant
  and category. Drops when a rule matches the wrong thing, which coverage
  alone would miss (a wrong match still "covers" the row).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "eval_set.jsonl")
DEFAULT_RULES = os.path.join(ROOT, "tests", "fixtures", "eval_rules.json")


@dataclass
class Case:
    description: str
    account: str
    kind: str
    expected_merchant: str
    expected_category: str


def load_cases(path: str) -> list[Case]:
    cases = []
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: {exc}")
            cases.append(Case(
                description=row["description"],
                account=row["account"],
                kind=row["kind"],
                expected_merchant=row["expected_merchant"],
                expected_category=row["expected_category"],
            ))
    return cases


@dataclass
class Miss:
    case: Case
    got_merchant: str
    got_category: str


@dataclass
class EvalResult:
    total: int = 0
    merchant_matches: int = 0
    category_matches: int = 0
    exact_matches: int = 0
    covered: int = 0     # expected categorized, and didn't fall through
    coverable: int = 0   # rows not expected to be uncategorized
    misses: list = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.exact_matches / self.total if self.total else 1.0

    @property
    def coverage(self) -> float:
        return self.covered / self.coverable if self.coverable else 1.0


def run(cases: list[Case], normalize) -> EvalResult:
    """Score ``cases`` against a ``normalize(description, account, kind)`` function."""
    result = EvalResult(total=len(cases))
    for case in cases:
        got_merchant, got_category = normalize(case.description, case.account, case.kind)
        merchant_ok = got_merchant == case.expected_merchant
        category_ok = got_category == case.expected_category
        result.merchant_matches += merchant_ok
        result.category_matches += category_ok
        if merchant_ok and category_ok:
            result.exact_matches += 1
        else:
            result.misses.append(Miss(case, got_merchant, got_category))
        if case.expected_category != "uncategorized":
            result.coverable += 1
            if got_category != "uncategorized":
                result.covered += 1
    return result


def report(result: EvalResult, verbose: bool = False) -> None:
    print(f"{result.total} cases")
    print(f"  merchant match:  {result.merchant_matches}/{result.total} "
          f"({result.merchant_matches / result.total:.1%})")
    print(f"  category match:  {result.category_matches}/{result.total} "
          f"({result.category_matches / result.total:.1%})")
    print(f"  exact match:     {result.exact_matches}/{result.total} "
          f"({result.accuracy:.1%})")
    print(f"  coverage:        {result.covered}/{result.coverable} "
          f"({result.coverage:.1%}) of rows expected to be categorized")

    if result.misses:
        print(f"\n{len(result.misses)} miss(es)"
              + ("" if verbose else " (rerun with -v to list them)"))
        if verbose:
            for miss in result.misses:
                print(f"  {miss.case.description!r}")
                print(f"      expected: ({miss.case.expected_merchant!r}, "
                      f"{miss.case.expected_category!r})")
                print(f"      got:      ({miss.got_merchant!r}, {miss.got_category!r})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", default=DEFAULT_FIXTURE,
                     help="labeled cases, JSON Lines (default: the shipped eval set)")
    ap.add_argument("--rules", default=DEFAULT_RULES,
                     help="rules.json to score against (default: shipped ruleset only, "
                          "no personal rules -- pass a real path to score your own)")
    ap.add_argument("--min-accuracy", type=float, default=None,
                     help="exit 1 if accuracy falls below this fraction (e.g. 0.9)")
    ap.add_argument("--min-coverage", type=float, default=None,
                     help="exit 1 if coverage falls below this fraction")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every miss")
    args = ap.parse_args(argv)

    # Force the ruleset regardless of what the process already loaded, so the
    # score never silently depends on whatever ran first in this interpreter.
    os.environ["STATEMENT_RULES"] = args.rules
    from statementproof import merchants
    merchants.reload_rules()

    cases = load_cases(args.fixture)
    result = run(cases, merchants.normalize)
    report(result, verbose=args.verbose)

    failed = False
    if args.min_accuracy is not None and result.accuracy < args.min_accuracy:
        print(f"\naccuracy {result.accuracy:.1%} is below the required "
              f"{args.min_accuracy:.1%}", file=sys.stderr)
        failed = True
    if args.min_coverage is not None and result.coverage < args.min_coverage:
        print(f"coverage {result.coverage:.1%} is below the required "
              f"{args.min_coverage:.1%}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
