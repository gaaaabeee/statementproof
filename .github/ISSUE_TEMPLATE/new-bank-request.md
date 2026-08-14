---
name: New bank or product request
about: Ask for support for a bank or account type this tool doesn't parse yet
title: "[new bank] "
labels: parser
---

> ## ⚠️ Do not attach your statement
>
> A statement PDF contains your account number, your balances, your address and
> every merchant you have paid. **Never upload one to a public issue** — not
> even a bank's own official specimen/sample statement. Maintainers will not
> ask for one, and issues containing one will be closed.
>
> Everything needed to start a new parser is below, and none of it identifies
> you or your bank balance.

## Which product

- Bank:
- Account type (e.g. "checking", "savings", "credit card"):
- Roughly how many statements you could test against, if support is added:

## What identifies this statement

A parser has to recognize a statement before it can read it. Look at the first
one or two pages and answer what you can:

- What is the summary block at the top called (e.g. "Account Summary",
  "Checking Summary")?
- Paste a few short, distinctive phrases that appear near the top of every
  statement from this bank — the kind of thing that would *never* appear on a
  statement from a different bank. Boilerplate like the bank's name and a
  customer-service phone number is usually enough; skip anything that includes
  your own name, address or account number.

## How the statement proves its own numbers

This tool never emits a number it can't check against something the statement
itself prints. Which of these does your statement do?

- [ ] Prints a running balance after every transaction (so each row can be
      checked on its own)
- [ ] Prints subtotals per section (e.g. "Total deposits", "Total
      withdrawals") that add up to a summary figure, but no running balance
- [ ] Something else — describe it

## Environment

- OS:
- Python version (`python -V`):
- Tool version or commit:
