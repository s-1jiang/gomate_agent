from fastapi import APIRouter, Request, Response

from app.api.dependencies import CurrentUser
from app.core.browser_session import check_browser_request

router = APIRouter(prefix="/api/v1/maps", tags=["maps"])


@router.get("/config")
def map_config(request: Request, response: Response, user: CurrentUser):
    settings = request.app.state.settings
    enabled = bool(settings.amap_js_api_key and settings.amap_js_security_code.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return {
        "provider": "amap",
        "search_enabled": bool(settings.amap_web_service_key.get_secret_value()),
        "display_enabled": enabled,
        "js_key": settings.amap_js_api_key if enabled else "",
        "security_proxy": "/api/v1/maps/_AMapService",
        "default_city": settings.default_city,
        "web_search_enabled": bool(settings.tavily_api_key.get_secret_value()),
    }


@router.get("/_AMapService/v4/map/styles", include_in_schema=False)
async def map_style(request: Request):
    # This fixed public style resource carries no user data. POI/business APIs are not proxied.
    check_browser_request(request)
    content, content_type = await request.app.state.map_style.fetch(request.query_params)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
