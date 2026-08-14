---
name: Statement not parsing
about: A statement fails to be identified, or fails its validation checks
title: "[parser] "
labels: parser
---

> ## ⚠️ Do not attach your statement
>
> A statement PDF contains your account number, your balances, your address and
> every merchant you have paid. **Never upload one to a public issue.**
> Maintainers will not ask for one, and issues containing one will be closed.
>
> Everything needed to fix a layout bug is below, and none of it identifies you.

## What the tool printed

Run with `--report` and paste the output for the affected statement(s) only.
Feel free to redact the amounts in the deltas — the check *names* are what
matter.

```
paste here
```

## Which product

- Bank:
- Account type (e.g. "Chase Total Checking", "Chase Freedom Unlimited"):
- Statement period (month and year is enough):
- Roughly how many statements are affected:

## If nothing was detected at all

Paste the `could not be identified` line. If you're willing, say which of these
phrases appear in the first two pages of your statement: `CHECKING SUMMARY`,
`Opening/Closing Date`, `Previous Balance`, `TRANSACTION DETAIL` — or describe
what the summary block is called instead.

## Environment

- OS:
- Python version (`python -V`):
- Tool version or commit:
