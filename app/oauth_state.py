"""Bounded single-process OAuth contexts; never serialized into browser cookies."""
from dataclasses import dataclass, field
import hmac
from threading import Lock
import time
from uuid import UUID

from app.errors import APIError
from app.security import csrf_binding, new_token, token_hash, valid_token


@dataclass(frozen=True)
class OAuthContext:
    provider: str
    browser_hash: str = field(repr=False)
    identity_binding: str = field(repr=False)
    expires_at: float
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    return_path: str = "/"
    claim_contract_id: UUID | None = None


class OAuthStateStore:
    def __init__(self, ttl=600, capacity=1024):
        self.ttl, self.capacity = ttl, capacity
        self.entries = {}
        self.lock = Lock()

    def create(self, provider, browser, member, guest, return_path, claim_contract_id):
        now = time.monotonic()
        with self.lock:
            self.entries = {key: value for key, value in self.entries.items() if value.expires_at > now}
            if len(self.entries) >= self.capacity:
                raise APIError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요.", retryable=True)
            state = new_token()
            context = OAuthContext(provider, token_hash(browser), csrf_binding(member, guest),
                                   now + self.ttl, new_token(), new_token(), return_path, claim_contract_id)
            self.entries[token_hash(state)] = context
            return state, context

    def consume(self, state, provider, browser, member, guest):
        failure = APIError(400, "INVALID_OAUTH_STATE", "로그인 요청이 만료됐거나 브라우저가 일치하지 않습니다.")
        if not valid_token(state) or not valid_token(browser):
            raise failure
        key = token_hash(state)
        with self.lock:
            context = self.entries.get(key)
            if context is None:
                raise failure
            if context.expires_at <= time.monotonic():
                del self.entries[key]
                raise failure
            if (context.provider != provider
                or not hmac.compare_digest(context.browser_hash, token_hash(browser))
                or not hmac.compare_digest(context.identity_binding, csrf_binding(member, guest))):
                raise failure
            del self.entries[key]
            return context
