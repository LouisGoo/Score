from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException


class ValidationIssue(BaseModel):
    code: str
    message: str
    field: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    issues: list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        retry_after: int | None = None,
        *,
        issues: list[ValidationIssue] | None = None,
    ):
        self.status, self.code, self.message = status, code, message
        self.retry_after = retry_after
        self.issues = issues


def error_response(request: Request, error: APIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or uuid4().hex
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    detail = {"code": error.code, "message": error.message}
    if error.issues is not None:
        detail["issues"] = [issue.model_dump() for issue in error.issues]
    return JSONResponse(
        status_code=error.status,
        content={"error": detail, "request_id": request_id},
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # 不信任客户端提交的 request_id，避免日志注入与冲突。
        request.state.request_id = uuid4().hex
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origins = request.headers.getlist("origin")
            if len(origins) != 1 or origins[0] not in app.state.settings.allowed_origins:
                return error_response(
                    request, APIError(403, "ORIGIN_FORBIDDEN", "请求来源不被允许")
                )
        try:
            response = await call_next(request)
        except Exception:
            # 不输出异常正文；其中可能有 SQL 参数、凭证或连接信息。
            return error_response(request, APIError(500, "INTERNAL_ERROR", "服务器内部错误"))
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(APIError)
    async def api_error(request: Request, error: APIError):
        return error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError):
        # 不回显 Pydantic 的 input/ctx，尤其是登录密码。
        return error_response(request, APIError(422, "VALIDATION_ERROR", "请求参数不合法"))

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, _error: SQLAlchemyError):
        return error_response(
            request, APIError(503, "SERVICE_UNAVAILABLE", "服务暂时不可用", retry_after=3)
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        response = error_response(
            request,
            APIError(error.status_code, codes.get(error.status_code, "HTTP_ERROR"), "请求无法处理"),
        )
        if error.headers and "Allow" in error.headers:
            response.headers["Allow"] = error.headers["Allow"]
        return response
