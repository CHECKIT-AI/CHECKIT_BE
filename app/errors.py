class APIError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 recovery_action: str = "NONE", retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.recovery_action = recovery_action
        self.retryable = retryable

    def content(self):
        return {"error": {"code": self.code, "message": self.message,
                          "recovery_action": self.recovery_action, "retryable": self.retryable}}


def unauthorized():
    return APIError(401, "AUTHENTICATION_REQUIRED", "인증이 필요하거나 세션이 만료됐습니다.", "LOGIN")


def not_found():
    return APIError(404, "CONTRACT_NOT_FOUND", "접근 가능한 계약서를 찾을 수 없습니다.")
