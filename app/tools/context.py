from dataclasses import dataclass

from app.core.identity import AuthContext


@dataclass(frozen=True)
class ToolContext:
    """Internal context, never an LLM business-argument model.

    Cross-process MCP transport will additionally require a short-lived signature
    bound to service and arguments; this dataclass alone is NOT authentication.
    """

    auth: AuthContext
    session_id: str
    run_id: str
    agent_name: str
    request_id: str
    scopes: frozenset[str]
