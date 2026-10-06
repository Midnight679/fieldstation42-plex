"""Remember files that would not start, so one damaged file cannot trap a channel.

A file that fails to start is retried a couple of times (a hiccup on the network should not condemn it). After that it
counts as bad for a while: the player skips it without trying, shows the channel's stand-by picture for the time it was meant
to run, and carries on with the rest of the schedule. After `RETRY_AFTER` seconds it gets another chance, so a file that
was only unreachable (the media server was down) comes back by itself. A file that plays clears its record.
"""

import logging
import threading
import time

_l = logging.getLogger("BadFiles")

FAILURES_BEFORE_SKIP = 2     # failed starts in a row before the file is skipped
RETRY_AFTER = 1800           # seconds a skipped file is left alone

_lock = threading.Lock()
_failures = {}               # path -> failed starts in a row
_skipped_at = {}             # path -> when it was given up on


def record_failure(path, now=None):
    """Note a failed start. Returns True when this failure is the one that makes the file skipped."""
    now = time.time() if now is None else now
    with _lock:
        _failures[path] = _failures.get(path, 0) + 1
        if _failures[path] >= FAILURES_BEFORE_SKIP and path not in _skipped_at:
            _skipped_at[path] = now
            _l.warning(f"Giving up on {path} for {RETRY_AFTER // 60} minutes after {_failures[path]} failed starts")
            return True
    return False


def is_bad(path, now=None):
    """True while the file is being skipped. Once the wait is over it is forgotten, so the next try counts afresh."""
    now = time.time() if now is None else now
    with _lock:
        since = _skipped_at.get(path)
        if since is None:
            return False
        if now - since >= RETRY_AFTER:
            del _skipped_at[path]
            _failures.pop(path, None)
            return False
        return True


def record_success(path):
    with _lock:
        _failures.pop(path, None)
        _skipped_at.pop(path, None)
