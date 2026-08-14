# Contributing

## Never send a statement

Statement PDFs contain account numbers, balances, addresses and a complete
record of where someone spends money. **Do not attach one to an issue, a pull
request, a test fixture or a commit.** Maintainers will not ask for one.

Everything needed to fix a parser is reproducible without one:

- the check names and deltas from `--report`
- which phrases appear in the statement's opening pages
- a synthetic file that mimics the layout, with invented values

CI fails the build if any `.pdf`, anything under `out/` or `statements/`, or a
personal `rules.json` is ever tracked by git.

## The one rule that matters

**Never emit a number you cannot prove.** Every parser must validate its own
output against totals the statement itself prints, and the run must refuse to
write when a check fails. A parser that returns plausible-looking wrong numbers
is worse than one that returns an error, because the error gets fixed and the
wrong number gets used.

If you cannot find a self-check for a format, say so in the pull request rather
than shipping without one.

## Adding a bank or a product

1. Write a parser module exposing `parse(path) -> Statement`, which appends a
   `Check` for every total the statement prints and can be reconciled against.
2. Add one `Format` to `formats.py`: `required` markers that rule it in,
   `markers` that add confidence, the account kind, and whether the account is
   an `ASSET` or a `LIABILITY` — the whole-corpus reconciliation weights
   accounts by that.
3. Add detection tests to `tests/test_formats.py` using representative *text*,
   not a PDF. Include a case asserting your format scores 0 against the other
   formats' text; mutual rejection is what stops one parser claiming another's
   statements.

Nothing else needs to change.

## Categorization rules

The shipped ruleset holds national brands and generic patterns only. Anything
naming a person, an employer, a landlord or a neighbourhood business belongs in
a user's own config file, not here — it is personal data about third parties who
did not agree to be in a public repository.

When adding to `RULES`, prefer a pattern that works for everyone (`\bPAYROLL\b`)
over one that works for you (`ACME CORP PAYROLL`).

Unrecognized merchants must stay `uncategorized`. A wrong category is worse than
an honest gap, because `--uncategorized` surfaces gaps and nothing surfaces a
confident mistake.

## Running things

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m statementproof.run --report --folder path/to/statements
```

Tests point `STATEMENT_RULES` at `tests/fixtures/rules.json`, so they never read
your personal config. If a test only passes with your own rules loaded, that is
a bug in the test.

## Dependencies

One runtime dependency, on purpose. Users point this at their entire financial
history; every package added is supply-chain risk on that data. A pull request
adding a dependency needs to justify why the standard library will not do.

No telemetry, no crash reporting, no update checks, no network calls of any
kind. "Your PDFs never leave your machine" is the project's core claim and a
single outbound request would make it false.
