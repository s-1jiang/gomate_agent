from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app import __version__
from app.api.dependencies import CurrentUser, DatabaseDep, TokenDep
from app.core.security import token_digest
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository
from app.schemas.api import (
    ConversationCreate,
    ConversationOut,
    Credentials,
    MessageCreate,
    MessageOut,
    RunOut,
    TokenOut,
    UserOut,
)
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1")
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/capabilities", tags=["system"])
def capabilities():
    return {
        "version": __version__,
        "stage": "foundation",
        "available": ["auth", "conversations", "message_persistence", "run_lifecycle"],
        "planned": ["planning_workflow", "mcp", "private_retrieval", "profiles", "map_ui"],
        "model_provider": "deepseek",
        "proposed_map_provider": "amap",
    }


@router.post("/auth/register", response_model=UserOut, status_code=201, tags=["auth"])
def register(body: Credentials, request: Request, database: DatabaseDep):
    return AuthService(AuthRepository(database), request.app.state.settings).register(
        body.username,
        body.password,
    )


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(body: Credentials, request: Request, database: DatabaseDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return AuthService(AuthRepository(database), request.app.state.settings).login(
        body.username,
        body.password,
        request.client.host if request.client else "unknown",
    )


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(database: DatabaseDep, user: CurrentUser, token: TokenDep):
    AuthRepository(database).revoke(token_digest(token))
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, tags=["auth"])
def me(database: DatabaseDep, token: TokenDep):
    return AuthRepository(database).authenticate(token_digest(token))


@router.post(
    "/conversations", response_model=ConversationOut, status_code=201, tags=["conversations"]
)
def create_conversation(body: ConversationCreate, database: DatabaseDep, user: CurrentUser):
    return ConversationRepository(database, user).create(body.title)


@router.get("/conversations", response_model=list[ConversationOut], tags=["conversations"])
def list_conversations(
    database: DatabaseDep,
    user: CurrentUser,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return ConversationRepository(database, user).list_conversations(limit, offset)


@router.delete("/conversations/{session_id}", status_code=204, tags=["conversations"])
def delete_conversation(session_id: str, database: DatabaseDep, user: CurrentUser):
    ConversationRepository(database, user).delete(session_id)
    return Response(status_code=204)


@router.get(
    "/conversations/{session_id}/messages", response_model=list[MessageOut], tags=["conversations"]
)
def list_messages(
    session_id: str,
    database: DatabaseDep,
    user: CurrentUser,
    limit: Limit = 50,
    after: Annotated[str | None, Query(max_length=128)] = None,
):
    return ConversationRepository(database, user).messages(session_id, limit, after)


@router.post(
    "/conversations/{session_id}/messages", response_model=RunOut, status_code=202, tags=["runs"]
)
def send_message(
    session_id: str,
    body: MessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    database: DatabaseDep,
    user: CurrentUser,
):
    repository = RunRepository(database, user)
    run, created = repository.accept(
        session_id,
        body.client_message_id,
        body.content,
        request.app.state.settings,
    )
    if created:
        background_tasks.add_task(repository.finish_scaffold, run["id"])
    return run


@router.get("/runs/{run_id}", response_model=RunOut, tags=["runs"])
def get_run(run_id: str, database: DatabaseDep, user: CurrentUser):
    return RunRepository(database, user).get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunOut, tags=["runs"])
def cancel_run(run_id: str, database: DatabaseDep, user: CurrentUser):
    return RunRepository(database, user).cancel(run_id)
