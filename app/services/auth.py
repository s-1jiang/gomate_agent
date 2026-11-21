import time

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password, new_token, token_digest, verify_password
from app.db.repositories import AuthRepository


class AuthService:
    def __init__(self, repository: AuthRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def register(self, username: str, password: str) -> dict:
        return self.repository.register(username, hash_password(password))

    def login(
        self, username: str, password: str, address: str, *, remember_me: bool = False
    ) -> dict:
        self.repository.reserve_login(username, address, self.settings)
        user = self.repository.find_user(username)
        if not verify_password(password, user["password_hash"] if user else None):
            raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
        token = new_token()
        ttl = (
            self.settings.remember_token_ttl_seconds
            if remember_me
            else self.settings.token_ttl_seconds
        )
        self.repository.store_token(
            token_digest(token),
            user["id"],
            time.time() + ttl,
        )
        return {"access_token": token, "expires_in": ttl}
