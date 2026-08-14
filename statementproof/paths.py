"""Where the app keeps a user's statements, output and settings.

The CLI works relative to the current project directory, which is right for a
checkout. The app is different: someone who downloaded it should not have their
financial PDFs land inside the install directory, where an upgrade, a reinstall
or a stray ``git clean`` could take them with it. So the app owns a library
under the platform's user-data location.

Per platform:

* macOS   ``~/Library/Application Support/statementproof/``
* Windows ``%LOCALAPPDATA%\\statementproof\\``
* Linux   ``$XDG_DATA_HOME/statementproof/`` or ``~/.local/share/statementproof/``

``$STATEMENTPROOF_HOME`` overrides all of it, which is what the tests use so
they never touch a real library.
"""

from __future__ import annotations

import os
import sys

APP_NAME = "statementproof"


def home() -> str:
    """Root of the app's managed library."""
    override = os.environ.get("STATEMENTPROOF_HOME")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


def statements_dir() -> str:
    return os.path.join(home(), "statements")


def out_dir() -> str:
    return os.path.join(home(), "out")


def settings_path() -> str:
    return os.path.join(home(), "settings.json")


def ensure_library() -> str:
    """Create the library on first run and return its root.

    Created 0700: this directory holds statement PDFs and a full transaction
    history, and on a shared machine the default umask is not tight enough.
    """
    root = home()
    for path in (root, statements_dir(), out_dir()):
        os.makedirs(path, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass        # best effort; Windows and some filesystems don't care
    return root
