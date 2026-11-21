from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.browser_session import BROWSER_HEADER, SESSION_COOKIE, check_browser_request
from app.core.errors import AppError
from app.core.identity import AuthContext
from app.core.security import token_digest
from app.db.database import Database
from app.db.repositories import AuthRepository

bearer = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_token(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> str:
    if credentials is not None:
        return credentials.credentials
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        check_browser_request(request)
        # Cookie credentials are ambient: unsafe requests must carry a custom header.
        # Cross-origin forms cannot set it; fetch would require a disallowed CORS preflight.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get(BROWSER_HEADER) != "web":
                raise AppError("CSRF_REQUIRED", "请从本站页面重新提交操作", 403)
        return cookie
    raise AppError("UNAUTHORIZED", "请先登录", 401)


TokenDep = Annotated[str, Depends(get_token)]


def get_current_user(database: DatabaseDep, token: TokenDep) -> AuthContext:
    user = AuthRepository(database).authenticate(token_digest(token))
    return AuthContext(user_id=user["id"], username=user["username"])


CurrentUser = Annotated[AuthContext, Depends(get_current_user)]
