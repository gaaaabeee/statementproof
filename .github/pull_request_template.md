<!--
  ┌────────────────────────────────────────────────────────────────────────┐
  │  STOP — READ BEFORE YOU TYPE ANYTHING BELOW                            │
  └────────────────────────────────────────────────────────────────────────┘
-->

## ⚠️ Before anything else: no real financial data

A statement PDF contains an account number, a balance, an address, and a
complete record of where a real person spends money. **A pull request is
public and permanent. A push cannot be un-pushed.**

Confirm all four. A PR that cannot check these will be closed, not fixed:

- [ ] **No statement PDF** — not attached, not committed, not renamed, not
      pasted, not "just for the test".
- [ ] **No real transaction text.** Descriptors, amounts, balances and dates
      copied off a real statement count as real data even without the PDF.
      Retype them with invented values.
- [ ] **No real names.** Not a person, a landlord, an employer, a neighbour, a
      local business, or a Zelle/Venmo counterparty — including your own.
      Personal rules belong in your own config file, never in this repo.
- [ ] **No `rules.json`** other than `tests/fixtures/rules.json`, and no
      generated output (`transactions.csv`, `by_category.csv`,
      `dashboard.html`, anything under `out/`).

> Everything needed to fix a parser is reproducible without a statement: the
> check names and deltas from `--report`, which phrases appear on the opening
> pages, and a synthetic file mimicking the layout with invented values. See
> [CONTRIBUTING.md](../CONTRIBUTING.md).
>
> CI enforces this, but **CI is the backstop, not the reviewer.** It catches
> files it recognizes; it cannot recognize your landlord's name.

---

## What this changes

<!-- One or two sentences. What problem, and why this approach. -->

## Proof

**The rule that matters: never emit a number you cannot prove.** If this PR
touches a parser, it must validate its own output against totals the statement
prints, and refuse to write when a check fails.

- [ ] Every number this produces is reconciled against a figure the statement
      itself prints — or this PR touches no parsing.
- [ ] If no self-check exists for this format, I have said so explicitly below
      rather than shipping without one.
- [ ] `python -m unittest discover -s tests` passes locally.
- [ ] New tests use **invented** values and representative *text*, not a PDF.

<!-- If a check is missing or a number is unproven, say so here. An honest gap
     is reviewable. A silent one is the failure this project exists to prevent. -->

## How this was verified

<!-- What did you actually run, and what did it output? "Tests pass" is not
     verification if the change is about numbers. -->
