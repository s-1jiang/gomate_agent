from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.identity import AuthContext
from app.core.security import token_digest
from app.db.database import Database
from app.db.repositories import AuthRepository

bearer = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if credentials is None:
        raise AppError("UNAUTHORIZED", "请先登录", 401)
    return credentials.credentials


TokenDep = Annotated[str, Depends(get_token)]


def get_current_user(database: DatabaseDep, token: TokenDep) -> AuthContext:
    user = AuthRepository(database).authenticate(token_digest(token))
    return AuthContext(user_id=user["id"], username=user["username"])


CurrentUser = Annotated[AuthContext, Depends(get_current_user)]
