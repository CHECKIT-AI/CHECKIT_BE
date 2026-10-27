"""Server-side authorization-code exchange. Raw provider errors/tokens never escape."""
import base64
from dataclasses import dataclass
import hashlib
import hmac
from urllib.parse import urlencode

from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import httpx

from app.errors import APIError
from app.config import valid_oauth_url


@dataclass(frozen=True)
class SocialIdentity:
    subject: str
    email: str | None = None


def provider_config(settings, provider):
    if provider == "kakao":
        client_id = settings.kakao_rest_api_key.get_secret_value()
        secret = settings.kakao_client_secret.get_secret_value()
        redirect = settings.kakao_redirect_uri
    else:
        client_id = settings.google_client_id.get_secret_value()
        secret = settings.google_client_secret.get_secret_value()
        redirect = settings.google_redirect_uri
    if not client_id or not secret or not valid_oauth_url(redirect, settings.environment):
        raise APIError(503, "OAUTH_NOT_CONFIGURED", "소셜 로그인 설정을 확인하세요.")
    from urllib.parse import urlsplit
    if urlsplit(redirect).path != f"/api/auth/oauth/{provider}/callback":
        raise APIError(503, "OAUTH_NOT_CONFIGURED", "소셜 로그인 콜백 주소를 확인하세요.")
    return client_id, secret, redirect


def authorization_url(settings, provider, state, context):
    client_id, _, redirect = provider_config(settings, provider)
    parameters = dict(response_type="code", client_id=client_id, redirect_uri=redirect, state=state)
    if provider == "google":
        parameters.update(scope="openid email profile", nonce=context.nonce,
                          code_challenge=base64.urlsafe_b64encode(hashlib.sha256(context.verifier.encode()).digest()).rstrip(b"=").decode(),
                          code_challenge_method="S256")
        base = "https://accounts.google.com/o/oauth2/v2/auth"
    else:
        base = "https://kauth.kakao.com/oauth/authorize"
    return base + "?" + urlencode(parameters)


def verify_google_identity(raw_token, client_id, nonce):
    transport = GoogleRequest()

    def timed_request(url, method="GET", body=None, headers=None, **kwargs):
        return transport(url, method=method, body=body, headers=headers, timeout=10)

    try:
        claims = id_token.verify_oauth2_token(raw_token, timed_request, client_id, clock_skew_in_seconds=10)
    except TransportError:
        raise APIError(503, "OAUTH_PROVIDER_UNAVAILABLE", "구글 인증 서버에 연결할 수 없습니다.", retryable=True) from None
    except (ValueError, GoogleAuthError):
        raise APIError(400, "OAUTH_IDENTITY_INVALID", "구글 인증 정보를 확인할 수 없습니다.") from None
    finally:
        transport.session.close()
    if (not isinstance(claims, dict) or not isinstance(claims.get("nonce"), str)
        or not claims["nonce"].isascii()
        or not hmac.compare_digest(claims["nonce"], nonce)
        or claims.get("azp", client_id) != client_id
        or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255):
        raise APIError(400, "OAUTH_IDENTITY_INVALID", "구글 인증 정보를 확인할 수 없습니다.")
    email = claims.get("email") if claims.get("email_verified") is True else None
    if not isinstance(email, str) or len(email) > 254:
        email = None
    return SocialIdentity(claims["sub"], email)


class ProviderClient:
    def exchange(self, settings, provider, code, context):
        client_id, secret, redirect = provider_config(settings, provider)
        data = dict(grant_type="authorization_code", code=code, client_id=client_id,
                    client_secret=secret, redirect_uri=redirect)
        if provider == "google":
            data["code_verifier"] = context.verifier
            endpoint = "https://oauth2.googleapis.com/token"
        else:
            endpoint = "https://kauth.kakao.com/oauth/token"
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.post(endpoint, data=data)
                token_data = self.json_response(response)
                if provider == "google":
                    raw = token_data.get("id_token")
                    if not isinstance(raw, str) or not 1 <= len(raw) <= 20000:
                        raise APIError(400, "OAUTH_IDENTITY_INVALID", "구글 인증 정보를 확인할 수 없습니다.")
                    return verify_google_identity(raw, client_id, context.nonce)
                access_token = token_data.get("access_token")
                if not isinstance(access_token, str) or not 1 <= len(access_token) <= 10000:
                    raise APIError(400, "OAUTH_IDENTITY_INVALID", "카카오 인증 정보를 확인할 수 없습니다.")
                user = self.json_response(client.get("https://kapi.kakao.com/v2/user/me",
                                                    headers={"Authorization": "Bearer " + access_token},
                                                    params={"property_keys": "[]"}))
                subject = user.get("id")
                if type(subject) is not int or subject <= 0:
                    raise APIError(400, "OAUTH_IDENTITY_INVALID", "카카오 인증 정보를 확인할 수 없습니다.")
                return SocialIdentity(str(subject))
        except httpx.HTTPError:
            raise APIError(503, "OAUTH_PROVIDER_UNAVAILABLE", "소셜 로그인 서버에 연결할 수 없습니다.", retryable=True) from None

    @staticmethod
    def json_response(response):
        if response.status_code == 429 or response.status_code >= 500:
            raise APIError(503, "OAUTH_PROVIDER_UNAVAILABLE", "소셜 로그인 서버 응답이 지연되고 있습니다.", retryable=True)
        if response.status_code != 200:
            raise APIError(400, "OAUTH_EXCHANGE_FAILED", "소셜 로그인 인증에 실패했습니다. 다시 시작해 주세요.")
        try:
            result = response.json()
        except ValueError:
            raise APIError(400, "OAUTH_EXCHANGE_FAILED", "소셜 로그인 응답을 확인할 수 없습니다.") from None
        if not isinstance(result, dict):
            raise APIError(400, "OAUTH_EXCHANGE_FAILED", "소셜 로그인 응답을 확인할 수 없습니다.")
        return result
