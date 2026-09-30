"""Time-sortable, prefixed identifiers, e.g. ``case_0006a1b2c3d4e5f6...``.

Format: ``<prefix>_<13 hex time (microseconds)><8 hex random>`` (21 hex chars).
IDs generated in one process are strictly increasing, so ordering by id is stable.
"""

import re
import secrets
import threading
import time

CASE = "case"
DOCUMENT = "doc"
EVIDENCE = "evd"
CONFLICT = "cfl"
RUN = "run"
STAGE = "stg"
RULE_RESULT = "rul"
REVIEW = "rev"
AUDIT = "aud"

_lock = threading.Lock()
_last = 0


def new_id(prefix: str) -> str:
    global _last
    with _lock:
        now = time.time_ns() // 1000
        if now <= _last:
            now = _last + 1
        _last = now
    return f"{prefix}_{now:013x}{secrets.token_hex(4)}"


def id_pattern(prefix: str) -> str:
    return rf"^{prefix}_[0-9a-f]{{21}}$"


def is_valid_id(value: str, prefix: str) -> bool:
    return bool(re.match(id_pattern(prefix), value or ""))
