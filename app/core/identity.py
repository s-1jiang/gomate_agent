from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    """Created by the authentication dependency, never accepted in request bodies."""

    user_id: str
    username: str
