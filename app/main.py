from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg
from psycopg_pool import PoolTimeout

from app.auth import router as auth_router
from app.api_docs import API_DESCRIPTION, ENDPOINTS, TAGS
from app.contracts import router as contracts_router
from app.config import Settings
from app.database import create_pool, verify_backend_role
from app.errors import APIError
from app.security import RateLimiter, hash_password, new_token
from app.oauth import OAuthCallbackRedactionMiddleware, router as oauth_router
from app.oauth_providers import ProviderClient
from app.oauth_state import OAuthStateStore


def create_app(settings: Settings | None = None, pool=None) -> FastAPI:
    resolved = settings or Settings()
    if not resolved.csrf_secret.get_secret_value():
        # Development only: restart invalidates CSRF contexts, not DB login sessions.
        from pydantic import SecretStr
        resolved = resolved.model_copy(update={"csrf_secret": SecretStr(new_token())})

    @asynccontextmanager
    async def lifespan(application):
        database_pool = pool if pool is not None else create_pool(resolved)
        database_pool.open()
        application.state.database_pool = database_pool
        try:
            yield
        finally:
            database_pool.close()

    application = FastAPI(title="CheckIt 백엔드 API", version="0.2.0", lifespan=lifespan,
                          description=API_DESCRIPTION, openapi_tags=TAGS,
                          swagger_ui_parameters={"withCredentials": True,
                                                 "defaultModelsExpandDepth": 1,
                                                 "displayRequestDuration": True})
    application.state.settings = resolved
    application.state.auth_limiter = RateLimiter()
    application.state.oauth_states = OAuthStateStore()
    application.state.oauth_client = ProviderClient()
    application.state.dummy_password_hash = hash_password("checkit-dummy-password")
    application.add_middleware(CORSMiddleware, allow_origins=resolved.allowed_origins,
                               allow_credentials=True, allow_methods=["GET", "POST"],
                               allow_headers=["Content-Type", "X-CSRF-Token"])
    application.add_middleware(OAuthCallbackRedactionMiddleware)

    @application.middleware("http")
    async def protect_auth_input(request, call_next):
        if request.url.path.startswith("/api/auth/"):
            if request.method == "POST":
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        return JSONResponse(status_code=413, content=APIError(
                            413, "REQUEST_TOO_LARGE", "요청 크기가 너무 큽니다."
                        ).content())
                request._body = bytes(body)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(APIError)
    async def api_error(request, exc):
        return JSONResponse(status_code=exc.status, content=exc.content())

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default input field can echo passwords/email verification tokens.
        return JSONResponse(status_code=422, content=APIError(
            422, "INVALID_INPUT", "요청 필드와 형식을 확인하세요."
        ).content())

    async def database_error(request, exc):
        return JSONResponse(status_code=503, content=APIError(
            503, "DATABASE_UNAVAILABLE", "데이터베이스 요청을 처리할 수 없습니다.", retryable=True
        ).content())

    application.add_exception_handler(psycopg.Error, database_error)
    application.add_exception_handler(PoolTimeout, database_error)
    application.include_router(auth_router)
    application.include_router(oauth_router)
    application.include_router(contracts_router)

    @application.get("/health/live", tags=["health"], **ENDPOINTS["live"])
    def live():
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"], **ENDPOINTS["ready"])
    def ready():
        try:
            with application.state.database_pool.connection() as connection:
                verify_backend_role(connection)
                connection.execute("SELECT id FROM checkit.contracts LIMIT 0")
        except Exception:
            # Driver errors can contain hosts/users/connection data. Do not return them.
            return JSONResponse(status_code=503, content={"error": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "데이터베이스 연결 또는 권한을 확인하세요.",
                "recovery_action": "NONE", "retryable": True,
            }})
        return {"status": "ok"}

    original_openapi = application.openapi

    def documented_openapi():
        schema = original_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if not isinstance(operation, dict):
                    continue
                for parameter in operation.get("parameters", []):
                    if parameter.get("in") == "header" and parameter.get("name") == "X-CSRF-Token":
                        # Already required by require_csrf at runtime (missing -> 403).
                        # Mark it required in the UI without changing the existing error contract.
                        parameter["required"] = True
        # FastAPI removes None values while building examples; keep the optional input visible.
        login_examples = schema["paths"]["/api/auth/login"]["post"]["requestBody"]["content"]["application/json"]["examples"]
        login_examples["claim"]["value"]["claim_contract_id"] = None
        return schema

    application.openapi = documented_openapi
    return application


app = create_app()
