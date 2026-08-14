# statementproof

Turn bank statement PDFs into transaction data you can actually trust, then
into a dashboard — entirely on your own machine.

**Reconciled, not scraped.** Every figure is checked against totals the
statement prints itself. If a single check fails, the tool writes nothing and
tells you which statement and which check. No credentials, no aggregator, no
network calls: your PDFs never leave your computer.

## Install

**Requirements:** Python 3.9 or newer, and one dependency (`pypdf`) which the
launcher installs for you. Works on macOS, Windows and Linux.

### 1. Get the code

Download the latest release and unzip it:

**[Releases → Source code (zip)](https://github.com/gaaaabeee/statementproof/releases/latest)**

Or clone it:

```bash
git clone https://github.com/gaaaabeee/statementproof
cd statementproof
```

### 2. Start the app

**macOS** — double-click **`launch-macos.command`**.

> macOS quarantines anything downloaded from the internet, so the first launch
> is blocked with *"cannot be opened because it is from an unidentified
> developer."* Either **right-click → Open → Open**, or clear the flag once:
> ```bash
> xattr -d com.apple.quarantine launch-macos.command
> ```
> If double-clicking does nothing at all, the zip lost the executable bit:
> ```bash
> chmod +x launch-macos.command
> ```

**Windows** — double-click **`launch-windows.bat`**. If SmartScreen warns,
choose *More info → Run anyway*.

**Any platform, from a terminal:**

```bash
pip install -r requirements.txt
python -m statementproof.app
```

The launcher finds a suitable Python, installs `pypdf` if it is missing, starts
a local server and opens your browser. Nothing is downloaded or uploaded beyond
that one pip install.

### 3. Use it

Drop PDFs on the page (or choose a folder), verify, label what's left, generate.
**Point it at whatever folder your downloads landed in** — statements are
identified by reading them, not by filename, and the search is recursive.
Anything unrecognized is listed with the reason, never guessed at.

## Command line

The app is a front end over a CLI that does everything on its own:

```bash
python -m statementproof.app                  # the app (opens your browser)
python -m statementproof.run --folder ~/Downloads/statements  # any folder
python -m statementproof.run                  # defaults to ./statements
python -m statementproof.run --report         # validate only, write nothing
python -m statementproof.run --strict         # non-zero exit if anything fails
python -m statementproof.run --uncategorized  # merchants that need a rule
python -m statementproof.run --out DIR        # write the tables somewhere else
python -m statementproof.dashboard            # build out/dashboard.html
python -m statementproof.eval -v              # score categorization against a labeled set
python -m unittest discover -s tests          # 109 tests
```

`pip install .` also puts `statementproof`, `statementproof-app` and
`statementproof-dashboard` on your path. (Use plain `pip install .` — the
editable install needs pip 21.3+, newer than macOS system Python ships.)

## The app

`python -m statementproof.app`, or double-click a launcher. It serves a page on
`127.0.0.1` and opens your browser — **a loopback socket, not a network call**.
Nothing is sent anywhere and it works offline.

Statements are copied into a managed library
(`~/Library/Application Support/statementproof/` on macOS, `%LOCALAPPDATA%` on
Windows, `$XDG_DATA_HOME` on Linux), so your PDFs never live in the install
directory. `$STATEMENTPROOF_HOME` overrides it.

Because a complete financial history sits behind that socket, it is defended as
if exposed: loopback-only bind, a session token on every request, a `Host` check
against DNS-rebinding, no CORS, and uploads gated on `%PDF` magic bytes. See
[SECURITY.md](SECURITY.md).

**Labeling** (step 3) lists every merchant no rule recognizes, worst-by-spend.
Pick a category and the rule is written to your config and applied immediately —
no restart. Rules match the *raw descriptor* while the list shows the *cleaned
name*, so each suggestion is verified before it is offered: it must cover every
row it targets and steal none that already have a category.

## Scope — read this before trying it

| Bank | Product | Verified against |
|---|---|---|
| Chase | Total Checking | 20 statements, 2024–2026 |
| Chase | Sapphire-family credit card | 20 statements, 2024–2026 |
| Bank of America | Adv Plus Banking (checking) | 6 statements, 2026 |

Both banks issue many other products, and have used other layouts historically.
Those may or may not parse — but an unsupported layout **fails loudly rather
than producing plausible-looking wrong numbers**, which is the entire point. If
your statements don't parse, that's a bug worth reporting.

Any number of accounts is supported: statements are grouped per account, each
checked independently for gaps and balance continuity.

## Validation

Parsing a PDF with regexes is only as good as its proof, so **nothing is written
unless every statement reconciles against numbers it prints itself**. If a check
fails the run refuses to write (`--force` overrides) and names the statement and
the check.

What that means per format depends on what the statement gives you. Chase
checking prints a running balance after every row, so every row is provable
individually. Neither Chase credit nor BoA does, so their printed section and
summary totals do the work instead — each bucket must equal the rows classified
into it, and the page totals must agree with the summary that claims to
summarize them. Exact checks live beside each parser in `_validate()`.

Then across statements: periods must be contiguous, closing balances must chain
into opening balances, and **the net of every signed amount must equal the
change in position across all accounts**, each weighted by whether it is an
asset or a debt. That last check ties the entire corpus to two numbers per
account, and only balances if the sign convention is right and no row is missing
or duplicated.

## Output

```
transactions.csv    every row, with merchant and category
statements.csv      one row per statement: summary figures and check results
by_category.csv     month × category
dashboard.html      self-contained; no CDN, no external assets, opens offline
```

The dashboard carries a period filter scoping every chart, money in vs money
out, monthly spending by category, account balances on one axis, interest and
fees, category and merchant breakdowns, detected recurring charges, and a
searchable transaction table.

**Two columns, deliberately.** `amount` is exactly what the statement prints, so
its meaning depends on the account (a card purchase prints positive). `signed`
normalizes to your point of view, which makes it double-entry consistent: a card
payment is negative in checking and positive on the card, so transfers cancel.
**Use `signed` for analysis, `amount` to tie back to paper.**

## What counts as spending

`run.spend_rows()` is the definition to reuse: card purchases, cash advances,
fees and interest, plus checking withdrawals — minus `Transfers`, `Refunds`,
`Income`, `Reimbursements` and `One-off deposits`. A card payment out of
checking is the same money as the purchases it settles, so counting both would
double-count.

Two judgements worth knowing about, because they change every total:

- **Person-to-person rails are spending, not transfers.** Zelle, Venmo and
  friends move money *out*; what it bought is decided by the counterparty, not
  the rail. Treating the rail as a transfer hides standing obligations — rent
  paid by Zelle becomes invisible. Money *received* the same way is a
  `Reimbursement`, not income.
- **Inflows are separated by what they actually are** — earned income,
  reimbursements, unattributed one-off deposits, and transfers from an account
  you already own (excluded). Lumping them together overstates earnings.

## Your own categorization rules

Rules naming real people, employers or local businesses are personal data, so
they live in a config file, not this repo. Location, first match wins:
`$STATEMENT_RULES`, then `$XDG_CONFIG_HOME/statementproof/rules.json`, then
`~/.config/statementproof/rules.json`, then `%APPDATA%\statementproof\rules.json`.

```json
{
  "payees":    { "ALEX": {"label": "Rent", "category": "Housing"} },
  "ach":       { "9876543210": {"merchant": "Rent", "category": "Housing"} },
  "merchants": [ {"pattern": "CORNER CAFE", "merchant": "Corner Cafe", "category": "Dining & Delivery"} ]
}
```

`payees` matches the counterparty of a person-to-person payment; `merchants` are
regexes against the raw descriptor, tried **before** the built-in rules so a
local rule always wins.

**Reach for `ach` first** for rent, payroll, insurance and utilities. It keys on
the ACH originator id (`CO ID:` / `PPD ID:` in the descriptor), which stays
constant while the surrounding text changes monthly. On one real account a
single `ach` entry categorized 31.6% of all spending — the landlord's descriptor
carried a new reference each month and had been fragmenting into six separate
"merchants".

Run `--uncategorized` to see what is worth adding, worst-by-spend first.
**Never commit this file.**

## How it works

Each module documents its own reasoning; start with the docstrings.

| Module | Responsibility |
|---|---|
| `formats.py` | scored detection registry — which parser owns a PDF |
| `checking.py`, `credit.py`, `boa.py` | one parser each; every one validates its own output |
| `merchants.py` | descriptor normalization, merchant rules, categories |
| `records.py` | `Txn` / `Statement` and the sign convention |
| `run.py` | discovery, cross-statement checks, CSV output |
| `dashboard.py`, `app.py`, `ui.py` | dashboard, local server, app page |

Adding a bank means one `Format` entry plus a parser exposing
`parse(path) -> Statement` that validates itself. Nothing else changes. See
[CONTRIBUTING.md](CONTRIBUTING.md).

Worth knowing if you touch the parsers: categorization fails far more often
because a descriptor was not unwrapped than because a merchant is unknown —
measured across two banks and two people, 78% of uncategorized spend was a
normalization failure. Unwrapping happens in three layers (bank envelope, ACH
tail, processor prefix), and unrecognized merchants are left `uncategorized`
rather than guessed at.

## Reporting a parsing problem

**Do not attach your statements to an issue.** They contain your account number,
balances and every merchant you have paid.

Include instead: the failing check names and deltas from `--report`, your bank
and product name, and the statement period. That fixes nearly every layout bug.

## License & disclaimer

MIT. Provided without warranty. Not financial, tax or accounting advice — always
verify figures against your original statements before relying on them.
