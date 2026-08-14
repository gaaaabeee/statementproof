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

APP_NAME = "statementproof"
FILENAME = "rules.json"

TEMPLATE = {
    "_comment": [
        "Personal categorization rules for statementproof.",
        "This file stays on your machine; never commit it to source control.",
        "payees: counterparty of a Zelle/Venmo-style payment -> label + category.",
        "merchants: regex against the raw statement descriptor -> merchant + category.",
        "User rules are checked before the built-in ones, so they always win.",
    ],
    "payees": {},
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
    path = config_path()
    if not os.path.exists(path):
        return {"payees": {}, "merchants": []}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(
            f"could not read rules file {path}: {exc}\n"
            "Fix the JSON or delete the file to start from an empty ruleset."
        )
    return {
        "payees": data.get("payees") or {},
        "merchants": data.get("merchants") or [],
    }


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
