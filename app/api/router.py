from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app import __version__
from app.api.dependencies import CurrentUser, DatabaseDep, TokenDep
from app.core.browser_session import (
    SESSION_COOKIE,
    check_browser_request,
    clear_browser_session,
    set_browser_session,
)
from app.core.security import token_digest
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository
from app.retrieval.repository import KnowledgeRepository
from app.schemas.api import (
    ConversationCreate,
    ConversationOut,
    Credentials,
    LoginCredentials,
    MessageCreate,
    MessageOut,
    RetrievalSource,
    RunOut,
    TokenOut,
    UserOut,
)
from app.schemas.knowledge import DocumentCreate, DocumentOut, KnowledgeSearch
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1")
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/capabilities", tags=["system"])
def capabilities():
    return {
        "version": __version__,
        "stage": "supervisor_map_search",
        "available": [
            "auth",
            "conversations",
            "message_persistence",
            "run_lifecycle",
            "text_chat",
            "private_text_knowledge",
            "retrieval_sources",
            "supervisor_dispatch",
            "supervisor_review",
            "map_search",
            "map_display",
        ],
        "planned": ["planning_workflow", "mcp", "private_retrieval", "profiles", "map_ui"],
        "retrieval_method": "lexical",
        "model_provider": "deepseek",
        "map_provider": "amap",
        "proposed_map_provider": "amap",
    }


@router.post("/auth/register", response_model=UserOut, status_code=201, tags=["auth"])
def register(body: Credentials, request: Request, database: DatabaseDep):
    check_browser_request(request)
    return AuthService(AuthRepository(database), request.app.state.settings).register(
        body.username,
        body.password,
    )


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(body: LoginCredentials, request: Request, database: DatabaseDep, response: Response):
    check_browser_request(request)
    response.headers["Cache-Control"] = "no-store"
    repository = AuthRepository(database)
    settings = request.app.state.settings
    result = AuthService(repository, settings).login(
        body.username,
        body.password,
        request.client.host if request.client else "unknown",
        remember_me=body.remember_me,
    )
    previous = request.cookies.get(SESSION_COOKIE)
    if previous:
        repository.revoke(token_digest(previous))
    if body.remember_me:
        set_browser_session(
            response, request, result["access_token"], result["expires_in"], settings
        )
    else:
        clear_browser_session(response)
    return result


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(request: Request, database: DatabaseDep, token: TokenDep):
    repository = AuthRepository(database)
    repository.revoke(token_digest(token))
    previous = request.cookies.get(SESSION_COOKIE)
    if previous and previous != token:
        repository.revoke(token_digest(previous))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    clear_browser_session(response)
    return response


@router.get("/me", response_model=UserOut, tags=["auth"])
def me(database: DatabaseDep, token: TokenDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
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
        background_tasks.add_task(request.app.state.chat.run, user, run["id"])
    return run


@router.get("/runs/{run_id}", response_model=RunOut, tags=["runs"])
def get_run(run_id: str, database: DatabaseDep, user: CurrentUser):
    return RunRepository(database, user).get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunOut, tags=["runs"])
async def cancel_run(run_id: str, request: Request, database: DatabaseDep, user: CurrentUser):
    result = RunRepository(database, user).cancel(run_id)
    request.app.state.chat.cancel(user, run_id)
    return result


@router.post(
    "/knowledge/documents",
    response_model=DocumentOut,
    status_code=201,
    tags=["knowledge"],
)
def create_document(body: DocumentCreate, database: DatabaseDep, user: CurrentUser):
    return KnowledgeRepository(database, user).create(body)


@router.get("/knowledge/documents", response_model=list[DocumentOut], tags=["knowledge"])
def list_documents(
    database: DatabaseDep,
    user: CurrentUser,
    session_id: Annotated[str | None, Query(max_length=128)] = None,
):
    return KnowledgeRepository(database, user).list_documents(session_id)


@router.delete("/knowledge/documents/{document_id}", status_code=204, tags=["knowledge"])
def delete_document(document_id: str, database: DatabaseDep, user: CurrentUser):
    KnowledgeRepository(database, user).delete(document_id)
    return Response(status_code=204)


@router.post("/knowledge/search", response_model=list[RetrievalSource], tags=["knowledge"])
def search_knowledge(body: KnowledgeSearch, database: DatabaseDep, user: CurrentUser):
    return KnowledgeRepository(database, user).search(body.session_id, body.query, body.limit)
