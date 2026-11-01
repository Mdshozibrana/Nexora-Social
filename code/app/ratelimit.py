"""In-memory sliding-window rate limiting — Phase 28, security §3/§6.

One process serves the whole platform (Render single instance), so a
per-process limiter is effective today; if the service ever scales
to multiple instances this must move to a shared store (Postgres or
Redis) — noted in SECURITY.md. Windows are sliding: each bucket keeps
the timestamps of the last `window` seconds of hits and rejects once
`limit` is reached. Rejected hits are NOT recorded, so a client that
backs off recovers as old hits age out."""
import threading
import time
from collections import deque

_lock = threading.Lock()
_buckets = {}


def hit(bucket: str, key: str, limit: int, window: float) -> bool:
    """Record one hit; return True when it is within the limit."""
    now = time.time()
    cutoff = now - window
    with _lock:
        # Second-pass audit (R4): keys of idle buckets used to live
        # forever in this long-lived process — drop emptied buckets
        # opportunistically once the map grows large.
        if len(_buckets) > 5000:
            for k in [k for k, dq in _buckets.items()
                      if not dq or dq[-1] < now - 86400]:
                _buckets.pop(k, None)
        dq = _buckets.get((bucket, key))
        if dq is None:
            dq = _buckets[(bucket, key)] = deque()
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


def reset():
    """Test helper: clear every bucket."""
    with _lock:
        _buckets.clear()
