"""錯誤格式：`{"error": {"code", "message", "retry_after_ms"?}}`。"""

import math

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.problem import Problem
from src.middleware.headers import SECURITY_HEADERS

INTERNAL_ERROR_MESSAGE = "無法完成模擬操作，請確認原操作結果"

# 框架層錯誤（路由不存在、方法不符等）對應的錯誤碼與訊息
_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    404: ("not_found", "找不到指定的 API"),
    405: ("method_invalid", "此 API 不支援這個請求方法"),
}


def problem_response(p: Problem) -> JSONResponse:
    error: dict[str, object] = {"code": p.code, "message": p.message}
    headers: dict[str, str] = {}
    if p.retry_after_ms is not None:
        error["retry_after_ms"] = p.retry_after_ms
        headers["Retry-After"] = str(math.ceil(p.retry_after_ms / 1000))
    return JSONResponse({"error": error}, status_code=p.status, headers=headers)


async def _handle_problem(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return problem_response(exc)


async def _handle_http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_ERRORS.get(exc.status_code, ("http_error", "無法處理這個請求"))
    # 保留框架給的標頭，例如 405 的 Allow
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _handle_validation_error(_request: Request, _exc: Exception) -> JSONResponse:
    # 驗證錯誤的細節含使用者送出的值，不回給客戶端
    return JSONResponse(
        {"error": {"code": "payload_invalid", "message": "請求內容格式不正確"}},
        status_code=422,
    )


async def _handle_unexpected(_request: Request, _exc: Exception) -> JSONResponse:
    # Exception 處理器在最外層的 ServerErrorMiddleware 執行，不會經過安全標頭 middleware，
    # 因此在這裡直接帶上。例外細節不回給客戶端；Starlette 回應後會再拋出，由伺服器記錄堆疊。
    return JSONResponse(
        {"error": {"code": "internal_error", "message": INTERNAL_ERROR_MESSAGE}},
        status_code=500,
        headers=SECURITY_HEADERS,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _handle_problem)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
