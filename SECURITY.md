# Security and privacy

## Design guarantees

- **No network access.** The tool makes no outbound requests: no telemetry, no
  crash reporting, no update checks, no analytics. The generated
  `dashboard.html` is fully self-contained — no CDN, no remote fonts, no
  external assets — so it renders with the network off.
- **No credentials.** Nothing here asks for a banking login, and it does not
  integrate with Plaid or any aggregator. It reads PDFs you already downloaded.
- **One dependency** (`pypdf`), to keep supply-chain exposure minimal on data
  this sensitive.
- **Nothing leaves the machine.** Input PDFs, generated CSVs and the dashboard
  all stay in local directories that are gitignored.

## Your data

- `statements/`, `out/` and every `*.pdf` are gitignored, and CI fails if any of
  them is ever tracked.
- Personal categorization rules live outside the repository, in
  `~/.config/statement-reconciler/rules.json`. That file names real people and
  payees. **Do not commit it, and do not paste it into an issue.**
- `out/` contains a complete transaction history. Treat that folder like the
  statements themselves. If your project directory is inside a cloud-synced
  folder (iCloud Drive, Dropbox, OneDrive), be aware that generated output syncs
  too.

## Reporting a vulnerability

Open a GitHub security advisory, or an issue for anything low-risk. Please
report privately if the issue could expose user data.

**Do not include a statement PDF, a `rules.json`, or real transaction rows in
any report.** A synthetic reproduction is always sufficient; if it is not, say
so and a maintainer will work out another way.

## What this tool does not do

It is not financial, tax or accounting advice, and it carries no warranty.
Verify figures against your original statements before relying on them —
including for anything you file or submit.
