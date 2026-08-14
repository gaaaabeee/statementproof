# statementproof

Turn bank statement PDFs into transaction data you can actually trust, then
into a dashboard — entirely on your own machine.

**Reconciled, not scraped.** Every figure is checked against totals the
statement prints itself. If a single check fails, the tool writes nothing and
tells you which statement and which check. No credentials, no aggregator, no
network calls: your PDFs never leave your computer.

```bash
python -m statementproof.run --folder ~/Downloads/statements  # any folder
python -m statementproof.run                  # defaults to ./statements
python -m statementproof.run --report         # validate only, write nothing
python -m statementproof.run --strict         # non-zero exit if anything fails
python -m statementproof.run --uncategorized  # merchants that need a rule
python -m statementproof.dashboard            # build out/dashboard.html
python -m unittest discover -s tests                # 64 tests
```

Requires Python 3.9+ and one dependency, `pypdf`.

```bash
git clone https://github.com/gaaaabeee/statementproof
cd statementproof
pip install -r requirements.txt          # then use `python -m ...` as above
pip install .                            # optional: installs the CLI commands
```

Installing the package adds `statementproof` and
`statementproof-dashboard` to your path. (`pip install -e .` needs pip
21.3 or newer -- the version bundled with macOS system Python is older, so use a
plain `pip install .` or upgrade pip first.)

**Point it at whatever folder your downloads landed in.** Statements are
identified by reading them, not by filename or folder, and the search is
recursive — a flat dump of PDFs and a nested tree both work. Any file it does
not recognize is listed as unidentified and skipped, never guessed at.

## Scope — read this before trying it

Parsers are written and verified against real statements from these products:

| Bank | Product | Verified against |
|---|---|---|
| Chase | Total Checking | 20 statements, 2024–2026 |
| Chase | Sapphire-family credit card | 20 statements, 2024–2026 |
| Bank of America | Adv Plus Banking (checking) | 6 statements, 2026 |

Both banks issue many other products (Chase Freedom, Amazon, Ink, Premier Plus,
College Checking; BoA Advantage Savings, credit cards, business accounts) and
have used other layouts historically. Those may or may not parse.

Because of how validation works, an unsupported layout **fails loudly rather
than producing plausible-looking wrong numbers** — which is the entire point of
the design. If your statements don't parse, that's a bug worth reporting, not a
reason to distrust the output you do get.

Any number of accounts is supported. Statements are grouped by account, each
account is checked independently for gaps and balance continuity, and the
dashboard draws one balance line per account.

## Format detection

`formats.py` is a registry. Each entry declares markers that identify it from
the opening pages of a PDF, which account kind it represents, and whether that
account is an asset or a debt (the whole-corpus reconciliation weights accounts
by that polarity).

Detection is scored, not first-match: a format is ruled out unless one of its
`required` markers appears, then each corroborating `marker` adds confidence.
Files that match nothing are reported. Detection reads the first three pages
rather than just page one, because some statements open with a notice page that
pushes the summary block to page two.

**Adding a bank** means adding one `Format` plus a parser module exposing
`parse(path) -> Statement` that validates its own output. Nothing else changes.

## Layout

```
statements/            statement PDFs (any structure; searched recursively)
statementproof/  the parser
out/                   generated CSVs and dashboard (gitignored)
```

Outputs: `transactions.csv` (every row), `statements.csv` (one row per statement
with its summary and check results), `by_category.csv` (month × category),
`dashboard.html`.

## Validation

Parsing a PDF with regexes is only as good as its proof, so nothing is written
unless every statement reconciles against numbers it prints itself. If any check
fails the run refuses to write (`--force` overrides).

**Chase checking** — the statement prints a running balance after every row,
which is the strongest check available:

- `running_balance_breaks` — walking each parsed amount forward from the opening
  balance must reproduce every printed balance. A dropped row, a duplicated row,
  or a misread digit all break this.
- `ending_balance` — opening + net of all rows == printed closing balance.
- `deposits_total` / `withdrawals_total` — against the page-1 summary buckets.

**Chase credit** — no running balance, so the page-1 summary does the work:

- `purchases_total`, `payments_total`, `cash_advances_total`, `fees_total`,
  `interest_total` — each printed bucket must equal the rows classified into it.
- `new_balance` — previous balance + everything parsed == printed new balance.
- `fees_page_agrees` / `interest_page_agrees` — the activity pages print their
  own subtotals; disagreeing with page 1 means a page went missing.

**Bank of America checking** — no running balance either, and the amounts are
only separated from their descriptions by column position, so this format is
read in layout mode and proved against the totals it prints:

- `deposits_total` / `subtractions_total` — each printed section total
  (`Total ATM and debit card subtractions -$3,474.03`) must equal the rows
  parsed under that section.
- `summary_agrees_*` — the page-1 summary must match the section totals it
  summarizes, so a section skipped entirely cannot pass unnoticed.
- `ending_balance` — opening + everything parsed == printed closing balance.
  This is the only check a zero-activity month has, and it still holds.

**Across statements** — `continuity()` checks that each period starts the day
after the previous ends and that closing balances chain into opening balances —
per account, so several accounts of the same kind are each checked on their own.
Then, across everything: the net of every signed amount must equal the change in
position over all accounts, each weighted by whether it is an asset or a debt.
That last check ties the entire corpus to two numbers per account, and only
balances if the sign convention is right and no row is missing or duplicated.

## Sign convention

`amount` is exactly what the statement prints, so its meaning depends on the
account: checking is signed from the account's point of view (deposit +,
withdrawal −), credit from the *card balance's* point of view (purchase +,
payment −).

`signed` normalizes to the account holder's point of view — `amount` for
checking, `-amount` for credit. That makes it double-entry consistent: a card
payment is negative in checking and an equal positive on the card, so transfers
cancel and accounts can be summed without double-counting spending.

**Use `signed` for analysis. Use `amount` when tying back to a paper statement.**

## Your own categorization rules

Rules that name real people, employers or local businesses are personal data, so
they live in a config file rather than in this repository. The shipped ruleset
contains only national brands and generic patterns.

Location (first match wins):

1. `$STATEMENT_RULES`
2. `$XDG_CONFIG_HOME/statementproof/rules.json`
3. `~/.config/statementproof/rules.json` (macOS, Linux)
4. `%APPDATA%\statementproof\rules.json` (Windows)

```json
{
  "payees": {
    "ALEX": {"label": "Rent", "category": "Housing"}
  },
  "ach": {
    "9876543210": {"merchant": "Rent", "category": "Housing"}
  },
  "merchants": [
    {"pattern": "ACME CORP PAYROLL", "merchant": "Acme Corp (payroll)", "category": "Income"},
    {"pattern": "CORNER CAFE", "merchant": "Corner Cafe", "category": "Dining & Delivery"}
  ]
}
```

`payees` matches the counterparty of a person-to-person payment. `merchants`
entries are regexes against the raw descriptor and are tried **before** the
built-in rules, so a local rule always wins.

**`ach` is the one to reach for first** for rent, payroll, insurance and
utilities. It keys on the ACH originator id — the `CO ID:` or `PPD ID:` printed
in the descriptor — which stays the same while the surrounding text changes
every month. On one real account, a single `ach` entry categorized 31.6% of all
spending, because the landlord's descriptor carried a different reference each
month and had been fragmenting into six separate "merchants". Run `--uncategorized` to see what
is worth adding, worst-by-spend first.

**Never commit this file.** It describes your financial relationships.

## Descriptor normalization

Categorization fails far more often because a descriptor was not unwrapped than
because a merchant is unknown. Measured across two banks and two people, 78% of
uncategorized spend was a normalization failure, not missing knowledge.

Three layers, in order:

1. **Bank envelope** — removed by the parser, because only a parser knows its
   own wrapper. BoA prints `CHECKCARD 0614 <merchant> <23-digit reference>`;
   Chase prints `Card Purchase 05/04 <merchant> Card 1218`. A shared cleanup
   that tried to handle both over-stripped, reducing one row to `Checkcard 0402`
   and losing the airline entirely. Parsers set `Txn.descriptor`; an empty
   value means there was nothing to unwrap.
2. **ACH tail** — shared, because ACH is a network standard rather than a bank
   format. See `strip_ach_tail` and the `ach` rules above.
3. **Processor prefix and location** — shared: `TST*`, `SQ *`, `DD *`, store
   numbers, phone numbers, URLs, city and state.

Statements also clip merchant names to a fixed width, so the shipped rules match
truncated forms (`WHOLEFDS`, `VICTORIA'S SECR`, `LUFTHAN`) alongside full ones.

## How categorization works

`merchants.py` collapses raw descriptors into merchants in two passes:

1. **`RULES`** — ordered (pattern, merchant, category) triples matched against
   the raw descriptor. Aggregators are *matched, not stripped*: removing the
   `LYFT *` prefix would leave "Ride Wed 11pm" as the merchant name.
2. **`clean()` + `CATEGORY_HINTS`** — for the long tail, strip processor prefix,
   store number, phone, URL, city and state, then infer a category from words in
   the surviving name.

Two payment processors settle the category on their own: `TST*` is Toast, which
serves restaurants only, and a leading `SP ` is a Shopify checkout.

**Unrecognized merchants are left `uncategorized` rather than guessed at.**

### Counting spending correctly

`spend_rows()` is the definition to reuse: card purchases, cash advances, fees
and interest, plus checking withdrawals — minus anything categorized
`Transfers`, `Refunds`, `Income`, `Reimbursements` or `One-off deposits`. A card
payment out of checking is the same money as the card purchases it settles, so
counting both would double-count.

**Person-to-person rails are spending, not transfers.** Zelle, Venmo, Meta Pay
and Apple Cash move money *out*, unlike a card payment that nets against its own
purchases, so what they bought is decided by the counterparty, not the rail.
Classifying the rail as a transfer hides standing obligations — rent paid by
Zelle is invisible in every total. Money *received* over the same rails is a
`Reimbursement`, not income.

`Transfers` means only movement between accounts the user controls: card
payments, other-bank transfers, brokerage moves. Brokerage transfers are
excluded from spending deliberately — that money moves into an asset rather than
being consumed.

### Money arriving is not all one thing

Inflows are classified on their own terms (`inflow()`), not by the merchant
rules — a merchant name on money *arriving* means a refund from them, not
spending at them.

| Category | What it is | Counted as "money in"? |
|---|---|---|
| `Income` | payroll, tax refunds | yes |
| `Reimbursements` | person-to-person received, resale payouts, card refunds | yes |
| `One-off deposits` | an unattributed lump | yes |
| `Transfers` | funding from an account you already own | **no** |

Lumping these together overstates earnings, sometimes badly. Keeping an
unattributed deposit visible in its own bucket is deliberate — it is neither
recurring nor earned, and burying it in "income" would flatter every ratio
computed from it.

## Notes on the source PDFs

Three things bite naive parsers and are handled deliberately:

1. **Wrapped rows (checking).** Long descriptions spill over up to three extra
   lines with the amounts on the last one. Rows that don't match alone are
   buffered and re-tested as lines are appended. pypdf's `layout` mode keeps them
   on one line but runs description into amount (`Card 0000-5.63682.48`), so the
   default extraction is joined instead.
2. **Section order (credit).** The default text layer emits each page's section
   headers *after* the rows they head, so sections can't be read from it. A
   second `layout`-mode pass builds a `(date, amount) -> section` map used only
   to label rows — which is how a cash advance is separated from purchases.
3. **Negative "interest".** An interest rebate prints as
   `PURCHASE INTEREST CHARGE -.23` but Chase books it under Payment/Credits and
   leaves Interest Charged at the gross figure. Any negative amount is therefore
   classified as a credit regardless of wording.

## Dashboard

`statementproof.dashboard` writes `out/dashboard.html` — a single file with the data
inlined. **No network requests, no CDN, no external assets.** Open it in a
browser; re-run after adding statements.

Period filter scoping every chart, money in vs money out, monthly spending
stacked by category, account balances on one shared axis, interest and fees per
statement, category and merchant breakdowns, detected recurring charges, and a
searchable transaction table. "Show data tables" reveals the numeric twin under
each chart.

**Recurring detection keys on cadence regularity, not amount stability**, using
median absolute deviation so one missed cycle doesn't disqualify a bill. Real
bills cluster tightly; merchants merely visited about monthly scatter. Amount
variance alone is the wrong test — an electricity bill swings 40% month to month
and is still a bill. Charges whose last occurrence is more than 2.5 cycles before
the data ends are marked **ended** and excluded from the monthly total.

## Reporting a parsing problem

**Do not attach your statements to an issue.** They contain your account number,
balances and every merchant you've paid.

Include instead: the failing check names and deltas from `--report`, your bank and
product name, and the statement period. That is enough to fix nearly every
layout bug.

## Adding new statements

Drop the PDF in the right folder and re-run. Discovery is by folder, not
filename, so naming only matters for sorting.

## License & disclaimer

MIT. This software is provided without warranty. It is not financial, tax or
accounting advice. Always verify figures against your original statements before
relying on them.
