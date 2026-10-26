import hashlib
import hmac
import secrets
import time
from collections import OrderedDict, deque
from threading import Lock

from app.errors import APIError


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def valid_token(value: str | None) -> bool:
    return bool(value and len(value) == 43 and all(
        char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value
    ))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024).hex()
    return f"scrypt$131072$8$1${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "131072", "8", "1") or len(salt) != 32 or len(digest) != 128:
            return False
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def csrf_binding(member: str, guest: str) -> str:
    return token_hash(f"{len(member)}:{member}:{guest}")


def sign_csrf(secret: str, context: str, member: str, guest: str, now: int | None = None) -> str:
    payload = f"{int(time.time()) if now is None else now}.{new_token()}"
    signature = hmac.new(secret.encode(),
                         f"{context}.{csrf_binding(member, guest)}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_csrf(secret: str, context: str, member: str, guest: str, token: str) -> bool:
    if not valid_token(context) or len(token) > 160:
        return False
    try:
        timestamp, nonce, signature = token.split(".")
        age = time.time() - int(timestamp)
        if age < 0 or age > 600 or not valid_token(nonce):
            return False
        expected = hmac.new(secret.encode(),
                            f"{context}.{csrf_binding(member, guest)}.{timestamp}.{nonce}".encode(),
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


class RateLimiter:
    """Bounded per-process limiter; one worker until a shared limiter is added."""
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, key: str, limit: int = 10, seconds: int = 60):
        now = time.monotonic()
        with self.lock:
            bucket = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while bucket and bucket[0] <= now - seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                raise APIError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요.", retryable=True)
            bucket.append(now)
            if len(self.entries) > 10000:
                self.entries.popitem(last=False)
