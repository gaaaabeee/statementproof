"""Local desktop app: a page served on loopback, opened in your browser.

    python -m statementproof.app

Why a browser and not a native window: file drag-and-drop is the feature that
makes this pleasant, and it comes free in HTML. The alternative on this
platform is Tk, which needs a Tcl extension for drag-and-drop and, on current
macOS, cannot open a window at all with Apple's bundled Tk 8.5. The dashboard is
already HTML, so this also means one rendering stack instead of two.

**This is a loopback socket, not a network call.** The server binds 127.0.0.1
only, on a kernel-assigned port, and dies with the process. Nothing is sent
anywhere, and the app works with the machine offline. Because the data behind
it is a complete financial history, the socket is defended as if it were
exposed:

* every request must carry the session token, including the first page load,
  so another local process cannot drive the API by guessing the port;
* the ``Host`` header must be the loopback address we are actually bound to,
  which blocks DNS-rebinding from a page in the same browser;
* no CORS headers are ever sent, so a foreign page cannot read a response;
* uploads must start with ``%PDF``, are size-capped, and are written under a
  sanitized basename inside the library.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser

from . import config, dashboard, formats, merchants, paths, run, ui
from .records import normalize

MAX_UPLOAD = 25 * 1024 * 1024        # a statement PDF is ~300KB; 25MB is slack
PDF_MAGIC = b"%PDF"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class State:
    """Everything the UI needs between requests, held in memory."""

    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(32)
        self.source = paths.statements_dir()
        self.statements: list = []
        self.matched: list = []
        self.unmatched: list = []
        self.parsed = False


STATE = State()


# --- helpers ----------------------------------------------------------------

def safe_name(name: str) -> str:
    """A filename that cannot escape the directory it is written into.

    The stem is truncated *before* the extension is reattached. Truncating
    afterwards would cut ".pdf" off a long name, and the file would import fine
    and then be invisible: discovery globs for ``*.pdf``.
    """
    name = os.path.basename(name.replace("\\", "/"))
    name = SAFE_NAME.sub("_", name).lstrip(".") or "statement.pdf"
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = stem[:110].rstrip("._-") or "statement"
    return stem + ".pdf"


def pick_folder_native() -> str:
    """Open the platform's folder chooser without adding a dependency.

    Tk is unavailable on this platform (see the module docstring), so each OS's
    own dialog is used. If none is available the UI falls back to a typed path.
    """
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt "Choose a folder of statements")'],
                capture_output=True, text=True, timeout=300)
            return out.stdout.strip()
        if sys.platform == "win32":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=300)
            return out.stdout.strip()
        for cmd in (["zenity", "--file-selection", "--directory"],
                    ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]):
            if shutil.which(cmd[0]):
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
    except Exception:
        return ""
    return ""


def detect_source(folder: str) -> dict:
    """Identify every PDF under a folder without parsing it."""
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"not a folder: {folder}"}
    matched, unmatched = run.discover(folder)
    STATE.source, STATE.matched, STATE.unmatched = folder, matched, unmatched
    STATE.parsed = False
    kinds: dict = {}
    for d in matched:
        kinds[d.format.label] = kinds.get(d.format.label, 0) + 1
    return {
        "ok": True,
        "folder": folder,
        "counts": kinds,
        "files": [{"name": os.path.basename(d.path), "format": d.format.label,
                   "score": d.score} for d in matched],
        "skipped": [{"name": os.path.basename(d.path), "why": d.describe()}
                    for d in unmatched],
    }


def verify() -> dict:
    """Parse and validate. Mirrors the CLI: a failure blocks everything after."""
    if not STATE.matched:
        return {"ok": False, "error": "no supported statements found"}
    stmts = [d.format.parse(d.path) for d in STATE.matched]
    STATE.statements = stmts
    STATE.parsed = True

    per = []
    failures = unparsed = 0
    for s in sorted(stmts, key=lambda s: (s.account, s.period_start)):
        bad = [{"check": c.name, "delta": round(c.delta, 2)} for c in s.checks if not c.ok]
        failures += len(bad)
        unparsed += len(s.unparsed)
        per.append({
            "file": os.path.basename(s.path),
            "account": f"{s.account} ···{s.account_last4}",
            "period": f"{s.period_start} … {s.period_end}",
            "rows": len(s.txns),
            "checks": len(s.checks),
            "failed": bad,
            "unparsed": [t for _, t in s.unparsed][:5],
        })

    problems = run.continuity(stmts)
    accounts = [{"label": run.label(k), "statements": len(v)}
                for k, v in sorted(run.accounts(stmts).items())]
    return {
        "ok": True,
        "statements": per,
        "accounts": accounts,
        "continuity": problems,
        "totals": {"statements": len(stmts),
                   "transactions": sum(len(s.txns) for s in stmts),
                   "failed_checks": failures,
                   "unparsed": unparsed,
                   "continuity_problems": len(problems)},
        "can_generate": failures == 0 and unparsed == 0 and not problems,
    }


# --- labeling ---------------------------------------------------------------

def _spend_rows() -> list:
    return run.spend_rows(STATE.statements)


def longest_common_substring(strings: list) -> str:
    """Longest run of characters shared by every string. Small inputs only."""
    if not strings:
        return ""
    shortest = min(strings, key=len)
    for size in range(len(shortest), 3, -1):
        for start in range(0, len(shortest) - size + 1):
            candidate = shortest[start:start + size]
            if all(candidate in s for s in strings):
                return candidate
    return ""


def suggest_rule(merchant: str) -> dict:
    """Propose a rule for a merchant, and prove it before offering it.

    Rules are matched against the *raw descriptor*, but the UI shows the
    *cleaned merchant name* -- different strings. A rule built naively from the
    display name can match nothing at all, and would fail silently. So each
    candidate is checked: it must match every row it is meant to cover, and must
    not capture a row that already has a different category.
    """
    rows = [t for t in _spend_rows()
            if normalize(t.match_text, t.account, t.kind)[0] == merchant]
    if not rows:
        return {"ok": False, "error": "no rows for that merchant"}

    texts = [t.match_text.upper() for t in rows]
    others = [t for t in _spend_rows() if t not in rows]

    # An ACH originator id is the better key when there is one: it survives the
    # descriptor text changing every month.
    originators = {merchants.ach_originator(t.match_text) for t in rows}
    originators.discard(None)
    ach = originators.pop() if len(originators) == 1 else None

    candidates = []
    escaped_name = re.escape(merchant.upper())
    candidates.append(escaped_name)
    common = longest_common_substring(texts)
    if common:
        candidates.append(re.escape(common.strip()))

    for pattern in candidates:
        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            continue
        if not all(rx.search(t) for t in texts):
            continue
        stolen = [t for t in others
                  if rx.search(t.match_text.upper())
                  and normalize(t.match_text, t.account, t.kind)[1] != "uncategorized"]
        if stolen:
            continue
        extra = [t for t in others if rx.search(t.match_text.upper())]
        return {
            "ok": True, "merchant": merchant, "pattern": pattern, "ach": ach,
            "matches": len(rows) + len(extra),
            "total": round(sum(-t.signed for t in rows + extra), 2),
            "sample": rows[0].match_text[:90],
        }
    return {"ok": False, "error": "could not derive a rule that matches only these rows",
            "ach": ach, "sample": rows[0].match_text[:90]}


def uncategorized() -> dict:
    if not STATE.parsed:
        return {"ok": False, "error": "verify first"}
    groups: dict = {}
    for t in _spend_rows():
        m, c = normalize(t.match_text, t.account, t.kind)
        if c != "uncategorized":
            continue
        g = groups.setdefault(m, {"merchant": m, "count": 0, "total": 0.0,
                                  "sample": t.match_text[:90], "ach": None,
                                  "guess": merchants.suggest_category(m)})
        g["count"] += 1
        g["total"] = round(g["total"] + -t.signed, 2)
        g["ach"] = g["ach"] or merchants.ach_originator(t.match_text)
    items = sorted(groups.values(), key=lambda g: -g["total"])
    return {"ok": True, "items": items,
            "categories": sorted(CATEGORIES),
            "remaining": round(sum(g["total"] for g in items), 2)}


CATEGORIES = [
    merchants.GROCERIES, merchants.DINING, merchants.GAS, merchants.TRANSPORT,
    merchants.TRAVEL, merchants.SHOPPING, merchants.ENTERTAINMENT,
    merchants.RECREATION, merchants.SUBSCRIPTIONS, merchants.UTILITIES,
    merchants.INSURANCE, merchants.HEALTH, merchants.PERSONAL, merchants.AUTO,
    merchants.GAMBLING, merchants.GOVERNMENT, merchants.HOUSING,
    merchants.HOUSEHOLD, merchants.PEOPLE, merchants.CASH, merchants.FEES,
    merchants.TRANSFERS, merchants.INCOME,
]


def save_label(payload: dict) -> dict:
    """Write one rule, then reload so it applies immediately."""
    merchant = (payload.get("merchant") or "").strip()
    category = (payload.get("category") or "").strip()
    label = (payload.get("label") or merchant).strip()
    if not merchant or category not in CATEGORIES:
        return {"ok": False, "error": "merchant and a known category are required"}

    suggestion = suggest_rule(merchant)
    use_ach = bool(payload.get("use_ach")) and suggestion.get("ach")
    try:
        if use_ach:
            config.add_ach_rule(suggestion["ach"], label, category)
            key = f"ACH {suggestion['ach']}"
        else:
            if not suggestion.get("ok"):
                return suggestion
            config.add_merchant_rule(suggestion["pattern"], label, category)
            key = suggestion["pattern"]
    except Exception as exc:
        return {"ok": False, "error": f"could not save rule: {exc}"}

    merchants.reload_rules()      # without this the rule silently does nothing
    return {"ok": True, "key": key, "label": label, "category": category,
            "applied": sum(1 for t in _spend_rows()
                           if normalize(t.match_text, t.account, t.kind)[1] == category)}


def generate() -> dict:
    """Write the tables and the dashboard -- but only if everything reconciles."""
    report = verify()
    if not report.get("ok"):
        return report
    if not report["can_generate"]:
        return {"ok": False, "error": "validation failed; nothing was written",
                "report": report}
    out = paths.out_dir()
    paths.ensure_library()
    run.write_tables(STATE.statements, out)
    payload = dashboard.build_payload(out)
    html = dashboard.TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    path = os.path.join(out, "dashboard.html")
    with open(path, "w") as fh:
        fh.write(html)
    os.chmod(path, 0o600)
    return {"ok": True, "out": out, "rows": payload["coverage"]["rows"]}


# --- HTTP -------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "statementproof"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # keep the console for real output
        pass

    # -- security gate --------------------------------------------------------
    def _authorized(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False                       # DNS-rebinding attempt
        token = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).get("t", [""])[0]
        token = token or (self.headers.get("X-Token") or "")
        return secrets.compare_digest(token, STATE.token)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # No CORS headers, deliberately: a foreign page must not read this.
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    # -- routes ---------------------------------------------------------------
    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            return self._send(403, b"forbidden", "text/plain")

        if route == "/":
            return self._send(200, ui.page(STATE.token).encode(), "text/html; charset=utf-8")
        if route == "/api/state":
            return self._json({"source": STATE.source,
                               "library": paths.home(),
                               "rules": config.config_path()})
        if route == "/api/pick-folder":
            folder = pick_folder_native()
            return self._json(detect_source(folder) if folder
                              else {"ok": False, "cancelled": True})
        if route == "/api/detect":
            return self._json(detect_source(STATE.source))
        if route == "/api/verify":
            return self._json(verify())
        if route == "/api/uncategorized":
            return self._json(uncategorized())
        if route == "/dashboard":
            path = os.path.join(paths.out_dir(), "dashboard.html")
            if not os.path.exists(path):
                return self._send(404, b"no dashboard yet", "text/plain")
            with open(path, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            return self._send(403, b"forbidden", "text/plain")

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return self._json({"ok": False, "error": "file too large"}, 413)
        body = self.rfile.read(length) if length else b""

        if route == "/api/upload":
            return self._json(self._upload(body))
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "bad JSON"}, 400)

        if route == "/api/use-folder":
            return self._json(detect_source(os.path.expanduser(payload.get("folder", ""))))
        if route == "/api/label":
            return self._json(save_label(payload))
        if route == "/api/generate":
            return self._json(generate())
        return self._send(404, b"not found", "text/plain")

    def _upload(self, body: bytes) -> dict:
        """One PDF, raw, with its name in a header. Simpler than multipart."""
        name = safe_name(self.headers.get("X-Filename") or "statement.pdf")
        if not body.startswith(PDF_MAGIC):
            return {"ok": False, "name": name, "error": "not a PDF"}
        dest_dir = paths.statements_dir()
        paths.ensure_library()
        dest = os.path.join(dest_dir, name)
        stem, ext = os.path.splitext(dest)
        n = 2
        while os.path.exists(dest):
            dest = f"{stem}-{n}{ext}"
            n += 1
        with open(dest, "wb") as fh:
            fh.write(body)
        os.chmod(dest, 0o600)
        return {"ok": True, "name": os.path.basename(dest)}


def serve() -> tuple:
    """Bind loopback on a kernel-assigned port. Returns (httpd, url)."""
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.socket.getsockname()[1]
    return httpd, f"http://127.0.0.1:{port}/?t={STATE.token}"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="statementproof desktop app")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser")
    ap.add_argument("--folder", metavar="DIR", help="start with this source folder")
    args = ap.parse_args(argv)

    paths.ensure_library()
    if args.folder:
        STATE.source = os.path.abspath(os.path.expanduser(args.folder))

    httpd, url = serve()
    # flush=True throughout: stdout is block-buffered when this is launched from
    # a .command file rather than a terminal, and the URL would not appear until
    # the process exited -- which is the one line the user actually needs.
    print("statementproof", flush=True)
    print(f"  library : {paths.home()}", flush=True)
    print(f"  rules   : {config.config_path()}", flush=True)
    print(f"  open    : {url}", flush=True)
    print("\nThis is a local server on 127.0.0.1 only. Nothing leaves this machine.",
          flush=True)
    print("Press Ctrl-C to quit.\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
