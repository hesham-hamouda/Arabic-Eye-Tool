"""In-tool error tracking for Arabic Eye Tool — stdlib only, no cloud.

Every caught or uncaught failure inside the app is appended as one
JSON line to app/errors.log (timestamp, location, type, message,
traceback), newest last, capped at 500 entries. Nothing leaves the PC.
"""
from __future__ import annotations

import datetime
import json
import os
import traceback

LOG_NAME = "errors.log"
MAX_ENTRIES = 500


def log_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_NAME)


def log_error(where: str, exc: BaseException | None = None,
              path: str | None = None) -> str:
    """Append one error entry; return the log file path."""
    path = path or log_path()
    if exc is None:
        tb = ""
        etype, msg = "Error", where
    else:
        tb = "".join(traceback.format_exception(type(exc), exc,
                                                exc.__traceback__))
        etype, msg = type(exc).__name__, str(exc)
    entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
             "where": where, "type": etype, "message": msg, "trace": tb}
    try:
        lines: list[str] = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-MAX_ENTRIES:]) + "\n")
    except Exception:
        pass
    return path


def error_count(path: str | None = None) -> int:
    """Number of entries currently in the log (0 when none)."""
    path = path or log_path()
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip())
    except Exception:
        return 0
