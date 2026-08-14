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

This applies even to a bank's own official specimen statement — the sample PDF
some banks publish for marketing or accessibility purposes, with an invented
name and invented numbers. It's a legitimate way to build a parser without a
real customer's data, but the rule about what gets *committed* doesn't bend
for it: pull the phrases and structure you need into a synthetic fixture the
same way every existing test file already does, never the PDF itself.

## The one rule that matters

**Never emit a number you cannot prove.** Every parser must validate its own
output against totals the statement itself prints, and the run must refuse to
write when a check fails. A parser that returns plausible-looking wrong numbers
is worse than one that returns an error, because the error gets fixed and the
wrong number gets used.

If you cannot find a self-check for a format, say so in the pull request rather
than shipping without one.

## Adding a bank or a product

Start from a real statement's actual text — yours, a volunteer's (never
committed, see above), or an official specimen (same rule). Writing detection
phrases or row patterns without having seen the real text is a guess, and this
project exists specifically to never ship one of those.

1. **Extract the text two ways**: `pypdf`'s default mode and
   `extraction_mode="layout"`. Every format added so far has needed a
   different one — Chase's columns survive the default extraction; Bank of
   America's collapse into one unbroken string without `layout` mode, because
   the column positions are the only thing separating a description from its
   amount. Check both before assuming which one you need.
2. **Identify the proof strategy the layout affords.** There are two in use,
   and every new format is one or the other:
   - *Row-by-row*, when the statement prints a running balance after every
     transaction (see `checking.py`). The strongest proof available — each row
     stands on its own.
   - *Section-and-summary*, when it doesn't (see `credit.py`, `boa.py`).
     Rows are proved in aggregate: each printed section total must equal the
     rows classified into it, and the summary must equal the sum of the
     sections. Four to six independent checks per statement, typically.
3. **Write the parser module**, exposing `parse(path) -> Statement`, appending
   a `Check` for every total reconciled under whichever strategy applies.
4. **Add one `Format` to `formats.py`**: `required` markers that rule it in,
   `markers` that add confidence, the account kind, and whether the account is
   an `ASSET` or a `LIABILITY` — the whole-corpus reconciliation weights
   accounts by that.
5. **Add detection tests** to `tests/test_formats.py` using representative
   *text*, not a PDF. Include a case asserting your format scores 0 against
   the other formats' text; mutual rejection is what stops one parser claiming
   another's statements.
6. **Run it against the real sample** with `--report` until every check
   passes. Only a synthetic, invented-value version of the same shapes goes
   into the committed test suite.
7. **Extend descriptor normalization only if the bank needs it.** A new
   channel-prefix format belongs in that bank's own envelope-stripping (see
   `boa.strip_envelope()` for the pattern) — the ACH-tail and processor-prefix
   layers in `merchants.py` are already bank-agnostic and should rarely need
   to change.
8. **Update the README's Scope table** with the new bank/product and how many
   real statements it was verified against.

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
