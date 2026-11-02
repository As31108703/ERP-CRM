"""Session cookie：`/api/v1` 底下的每個請求都帶一個 64 位小寫 hex 權杖。

這個 middleware 只處理 cookie，不碰資料庫，也不拋出 Problem：
- 請求沒有 cookie、或格式不對時，產生新權杖；
- 權杖放在 `request.state.session_token`，由命令管線與 `touch_session` 對應到資料庫的 session 列；
- 每個回應都重新寫入 cookie，延長 Max-Age。
"""

import hashlib
import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request, cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config.settings import Settings
from src.core.ids import token_hex

COOKIE_NAME = "erpcrm_session"
MAX_AGE_PUBLIC_DEMO = 259_200  # 72 小時
MAX_AGE_PRIVATE = 31_536_000  # 365 天
_TOKEN_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SCOPED_PREFIX = "/api/v1/"


def hash_token(token: str) -> str:
    """資料庫只存權杖的 sha256。"""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def session_token(request: Request) -> str:
    token = getattr(request.state, "session_token", None)
    if not isinstance(token, str):
        raise RuntimeError("session middleware 未套用到這個路徑")
    return token


def _read_token(headers: Headers) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    # 用與瀏覽器相容的寬鬆解析：SimpleCookie 遇到同站其他不合 RFC 的 cookie
    # 會整串放棄，導致 session 權杖遺失
    token = cookie_parser(raw).get(COOKIE_NAME)
    if token is None or _TOKEN_RE.fullmatch(token) is None:
        return None
    return token


def _first(value: str | None) -> str:
    # X-Forwarded-* 經過多層代理時是逗號分隔清單，以最前面（最接近客戶端）的為準
    return (value or "").split(",")[0].strip()


def request_scheme(scope: Scope, headers: Headers) -> str:
    return (_first(headers.get("x-forwarded-proto")) or scope.get("scheme", "http")).lower()


def cookie_header(token: str, settings: Settings, secure: bool) -> str:
    max_age = MAX_AGE_PUBLIC_DEMO if settings.app.public_demo else MAX_AGE_PRIVATE
    value = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
    return value + "; Secure" if secure else value


class SessionCookieMiddleware:
    """純 ASGI middleware：解析或產生 session 權杖，並在回應寫入 cookie。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(_SCOPED_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        token = _read_token(headers) or token_hex(32)
        scope.setdefault("state", {})["session_token"] = token
        settings: Settings = scope["app"].state.settings
        cookie = cookie_header(token, settings, request_scheme(scope, headers) == "https")

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_cookie)
