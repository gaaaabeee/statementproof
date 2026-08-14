# Security and privacy

## Design guarantees

- **No network access.** The tool makes no outbound requests: no telemetry, no
  crash reporting, no update checks, no analytics.
- **The app's server is loopback-only.** `statementproof.app` binds `127.0.0.1`
  on a kernel-assigned port and dies with the process. It is a local UI
  transport, not a network call, and it works offline. Because it fronts a
  complete financial history it is hardened as if exposed:
  - a per-session token (`secrets.token_urlsafe`) is required on every request,
    including the first page load, so another local process cannot drive the
    API by finding the port;
  - the `Host` header must be loopback, which blocks DNS-rebinding from a page
    in the same browser;
  - no CORS headers are ever sent, so a foreign origin cannot read a response;
  - uploads must begin with `%PDF`, are size-capped, and are written under a
    sanitized basename that cannot escape the library. The generated
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
- The app's library (statements, CSVs, dashboard) lives under the platform user
  data directory, created `0700`, with statement PDFs and the dashboard written
  `0600`. `$STATEMENTPROOF_HOME` relocates it.
- **On Windows those POSIX modes do not apply** — `os.chmod` there only toggles
  the read-only bit. Protection comes instead from the ACL inherited from
  `%LOCALAPPDATA%` / `%APPDATA%`, which is already user-only by default. The
  `chmod` calls are best-effort and never fail a write.
- Personal categorization rules live outside the repository, in
  `~/.config/statementproof/rules.json`. That file names real people and
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
