from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException

from app import __version__
from app.api.maps import router as maps_router
from app.api.router import router
from app.core.browser_session import SESSION_COOKIE, clear_browser_session
from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database
from app.db.repositories import interrupt_pending_runs
from app.integrations.deepseek import DeepSeekClient
from app.integrations.map_style import MapStyleProxy
from app.observability.http import request_context
from app.services.chat import ChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    database = Database(config.database_path)
    chat = ChatService(database, config, DeepSeekClient(config))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.migrate()
        interrupt_pending_runs(database)
        try:
            yield
        finally:
            await chat.close()

    application = FastAPI(
        title=config.app_name,
        version=__version__,
        lifespan=lifespan,
        description="GoMate：Supervisor 地点搜索、文字聊天和可追溯来源。路线规划尚未接入。",
    )
    application.state.settings = config
    application.state.database = database
    application.state.chat = chat
    application.state.map_style = MapStyleProxy(config)
    application.middleware("http")(request_context)

    def error_response(request: Request, code: str, message: str, status: int, details=None):
        error = {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
        if details is not None:
            error["details"] = details
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        response = JSONResponse({"error": error}, status_code=status, headers=headers)
        if (
            status == 401
            and request.cookies.get(SESSION_COOKIE)
            and request.url.path != "/api/v1/auth/login"
        ):
            clear_browser_session(response)
        return response

    @application.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return error_response(request, exc.code, exc.message, exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo raw inputs: validation failures can contain passwords or tokens.
        details = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in exc.errors()
        ]
        return error_response(request, "INVALID_ARGUMENT", "请求参数不合法", 422, details)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, f"HTTP_{exc.status_code}", str(exc.detail), exc.status_code)

    @application.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @application.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "version": __version__}

    @application.get("/health/ready", tags=["health"])
    def ready():
        with database.connect() as connection:
            connection.execute("SELECT version FROM schema_migrations LIMIT 1").fetchone()
        return {"status": "ok", "database": "sqlite"}

    application.include_router(router)
    application.include_router(maps_router)
    return application


app = create_app()
