from fastapi import Request, Response

from app.core.config import Settings
from app.core.errors import AppError

SESSION_COOKIE = "gomate_remember"
COOKIE_PATH = "/api/v1"
BROWSER_HEADER = "X-GoMate-Request"


def check_browser_request(request: Request) -> None:
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError("CROSS_SITE_REQUEST", "请从本站页面发起操作", 403)


def clear_browser_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH, httponly=True, samesite="lax")


def set_browser_session(
    response: Response, request: Request, token: str, ttl: int, settings: Settings
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure or request.url.scheme == "https",
    )
