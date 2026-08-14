"""User-supplied categorization rules, loaded from a config file.

Rules that name real people, employers or local businesses are *personal data*.
They belong to whoever runs the tool, not to the project, so they live in a
config file outside the source tree and the shipped ruleset ships empty of them.

Location (first match wins):

1. ``$STATEMENT_RULES`` -- an explicit path, used by the tests
2. ``$XDG_CONFIG_HOME/statementproof/rules.json``
3. ``~/.config/statementproof/rules.json``           (macOS, Linux)
4. ``%APPDATA%\\statementproof\\rules.json``           (Windows)

Format -- every field optional::

    {
      "payees": {
        "SOME NAME": {"label": "Rent", "category": "Housing"}
      },
      "merchants": [
        {"pattern": "CORNER CAFE", "merchant": "Corner Cafe", "category": "Dining & Delivery"}
      ]
    }

``payees`` keys are matched against the counterparty of a person-to-person
payment (Zelle, Venmo and friends), case-insensitively, at the start of the
name. ``merchants`` entries are regular expressions matched against the raw
statement descriptor, and are tried *before* the built-in rules so a user can
always override a shipped guess.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile

APP_NAME = "statementproof"
FILENAME = "rules.json"

TEMPLATE = {
    "_comment": [
        "Personal categorization rules for statementproof.",
        "This file stays on your machine; never commit it to source control.",
        "payees: counterparty of a Zelle/Venmo-style payment -> label + category.",
        "merchants: regex against the raw statement descriptor -> merchant + category.",
        "ach: ACH originator id (CO ID / PPD ID on the statement) -> merchant + category.",
        "  Prefer ach over merchants for rent, payroll and utilities: the id is",
        "  stable while the descriptor text changes every month.",
        "User rules are checked before the built-in ones, so they always win.",
    ],
    "payees": {},
    "ach": {},
    "merchants": [],
}


def config_path() -> str:
    override = os.environ.get("STATEMENT_RULES")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME, FILENAME)


def ensure_config() -> str:
    """Create an empty rules file if none exists. Returns its path."""
    path = config_path()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(TEMPLATE, fh, indent=2)
            fh.write("\n")
    return path


def load() -> dict:
    """Read the rules file. A missing file is normal; a broken one is not."""
    return _sections(read_raw())


def read_raw() -> dict:
    """The file exactly as written, including any keys this version ignores.

    ``load()`` narrows to the sections the categorizer uses. Saving must not go
    through that narrowing, or hand-written comments and any section added by a
    newer version would be silently dropped on the next write.
    """
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(
            f"could not read rules file {path}: {exc}\n"
            "Fix the JSON or delete the file to start from an empty ruleset."
        )


def _sections(data: dict) -> dict:
    return {
        "payees": data.get("payees") or {},
        "ach": data.get("ach") or {},
        "merchants": data.get("merchants") or [],
    }


def save(data: dict) -> str:
    """Write the rules file atomically, 0600. Returns the path.

    Atomic because this file is edited while the app is running: a crash or a
    full disk midway through a plain write would leave truncated JSON, and
    ``load()`` treats unreadable JSON as fatal. Writing to a temp file in the
    same directory and renaming means the file is either the old one or the new
    one, never half of either.
    """
    path = config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, 0o600)          # it names real people and payees
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def _with_defaults(raw: dict) -> dict:
    """Fill in the sections and the explanatory comment for a fresh file."""
    if not raw:
        raw = dict(TEMPLATE)
    raw.setdefault("_comment", TEMPLATE["_comment"])
    raw.setdefault("payees", {})
    raw.setdefault("ach", {})
    raw.setdefault("merchants", [])
    return raw


def add_merchant_rule(pattern: str, merchant: str, category: str) -> str:
    """Add or replace a merchant rule, keyed on its pattern."""
    re.compile(pattern)               # fail here rather than on next load
    raw = _with_defaults(read_raw())
    entry = {"pattern": pattern, "merchant": merchant, "category": category}
    rules = [r for r in raw["merchants"]
             if not (isinstance(r, dict) and r.get("pattern") == pattern)]
    rules.append(entry)
    raw["merchants"] = rules
    return save(raw)


def add_ach_rule(originator: str, merchant: str, category: str) -> str:
    """Add or replace a rule keyed on an ACH originator id."""
    raw = _with_defaults(read_raw())
    raw["ach"][str(originator).strip().upper()] = {
        "merchant": merchant, "category": category,
    }
    return save(raw)


def remove_merchant_rule(pattern: str) -> str:
    raw = _with_defaults(read_raw())
    raw["merchants"] = [r for r in raw["merchants"]
                        if not (isinstance(r, dict) and r.get("pattern") == pattern)]
    return save(raw)


def compiled_payees(data: dict) -> list:
    """[(compiled_prefix_pattern, label, category)] from the payees table."""
    out = []
    for name, spec in data.get("payees", {}).items():
        if not isinstance(spec, dict):
            continue
        label = spec.get("label") or name.title()
        category = spec.get("category")
        if not category:
            continue
        out.append((re.compile(r"^" + re.escape(name), re.I), label, category))
    return out


def ach_rules(data: dict) -> dict:
    """{originator_id: (merchant, category)} from the ach table.

    Keying on the ACH originator id rather than the payee text is the more
    durable rule: the id is assigned to the originator and does not change when
    the descriptor text does.
    """
    out = {}
    for key, spec in data.get("ach", {}).items():
        if not isinstance(spec, dict):
            continue
        merchant, category = spec.get("merchant"), spec.get("category")
        if merchant and category:
            out[str(key).strip().upper()] = (merchant, category)
    return out


def compiled_merchants(data: dict) -> list:
    """[(compiled_pattern, merchant, category)] from the merchants list."""
    out = []
    for entry in data.get("merchants", []):
        if not isinstance(entry, dict):
            continue
        pattern, merchant = entry.get("pattern"), entry.get("merchant")
        category = entry.get("category")
        if not (pattern and merchant and category):
            continue
        try:
            out.append((re.compile(pattern, re.I), merchant, category))
        except re.error as exc:
            raise SystemExit(
                f"invalid regex in {config_path()}: {pattern!r} -- {exc}"
            )
    return out
