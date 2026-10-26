from email.message import EmailMessage
import smtplib
import ssl
from urllib.parse import urlencode

from app.errors import APIError


def ensure_mail_config(settings):
    if not settings.smtp_host or not settings.smtp_from or not settings.verification_page_url:
        raise APIError(503, "EMAIL_NOT_CONFIGURED", "이메일 인증 발송 설정이 필요합니다.")
    if not settings.verification_page_url.startswith("https://") and not (
        settings.environment == "development" and settings.verification_page_url.startswith(
            ("http://127.0.0.1:", "http://localhost:"))
    ):
        raise APIError(503, "EMAIL_NOT_CONFIGURED", "이메일 인증 화면 주소 설정을 확인하세요.")
    if "?" in settings.verification_page_url or "#" in settings.verification_page_url:
        raise APIError(503, "EMAIL_NOT_CONFIGURED", "이메일 인증 화면 주소 설정을 확인하세요.")


def send_verification(settings, address: str, token: str):
    message = EmailMessage()
    message["Subject"] = "CheckIt 이메일 인증"
    message["From"] = settings.smtp_from
    message["To"] = address
    # Fragment keeps token out of normal HTTP access logs. Frontend must read and clear it.
    link = settings.verification_page_url + "#" + urlencode({"token": token})
    message.set_content(f"CheckIt 가입을 완료하려면 다음 주소에서 인증을 확인해 주세요.\n{link}\n24시간 동안 유효합니다.")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)
