"""Show local configuration readiness without printing credentials or calling providers."""
from urllib.parse import urlsplit

from app.config import Settings, valid_oauth_url


def main():
    settings = Settings()
    ready = True
    for name in ("kakao_rest_api_key", "kakao_client_secret", "google_client_id", "google_client_secret"):
        configured = bool(getattr(settings, name).get_secret_value().strip())
        print(f"CHECKIT_{name.upper()}: {'입력됨' if configured else '미설정'}")
        ready = ready and configured
    for name, provider in (("kakao_redirect_uri", "kakao"), ("google_redirect_uri", "google")):
        value = getattr(settings, name)
        valid = valid_oauth_url(value, settings.environment) and urlsplit(value).path == f"/api/auth/oauth/{provider}/callback"
        print(f"CHECKIT_{name.upper()}: {'형식 확인' if valid else '설정 확인 필요'}")
        ready = ready and valid
    print("프론트 완료 주소: " + ("입력됨" if settings.oauth_frontend_complete_url else "미정 (개발용 완료 화면 사용 가능)"))
    print("설정 입력 여부만 확인했습니다. 개발자 콘솔 등록·실제 로그인 검증은 별도입니다.")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
