import time
import threading
from functools import wraps
from flask import request, jsonify


class RateLimiter:
    """Rate limiter in-memory por IP. Limpa entradas a cada 60s."""

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup(self):
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        cutoff = now - 300
        with self._lock:
            for key in list(self._store.keys()):
                entries = [t for t in self._store[key] if t > cutoff]
                if entries:
                    self._store[key] = entries
                else:
                    del self._store[key]

    def is_limited(self, key: str, max_attempts: int, window: int) -> bool:
        now = time.time()
        self._cleanup()
        with self._lock:
            entries = self._store.get(key, [])
            entries = [t for t in entries if t > now - window]
            if len(entries) >= max_attempts:
                return True
            entries.append(now)
            self._store[key] = entries
            return False

    def remaining(self, key: str, max_attempts: int, window: int) -> int:
        now = time.time()
        with self._lock:
            entries = self._store.get(key, [])
            entries = [t for t in entries if t > now - window]
            return max(0, max_attempts - len(entries))

    def reset(self, key: str):
        with self._lock:
            self._store.pop(key, None)


limiter = RateLimiter()


def rate_limit(max_attempts: int = 5, window: int = 300, key_func=None):
    """Decorator de rate limit. key_func(request) -> str. Default: IP."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if key_func:
                key = key_func(request)
            else:
                ip = request.headers.get("X-Forwarded-For", request.remote_addr)
                if ip and "," in ip:
                    ip = ip.split(",")[0].strip()
                key = f"{f.__name__}:{ip}"

            if limiter.is_limited(key, max_attempts, window):
                remaining = limiter.remaining(key, max_attempts, window)
                retry_after = window
                return jsonify({
                    "error": "Muitas tentativas. Aguarde alguns minutos.",
                    "retry_after": retry_after,
                }), 429
            return f(*args, **kwargs)
        return decorated
    return decorator
