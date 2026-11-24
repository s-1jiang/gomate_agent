import httpx

from app.integrations.map_style import MapStyleProxy


def test_only_public_browser_key_is_returned_to_authenticated_user(client, settings, login):
    assert client.get("/api/v1/maps/config").status_code == 401
    settings.amap_js_api_key = "fake-js-public-key"
    settings.amap_js_security_code = "PRIVATE_JS_SECRET_CANARY"
    settings.amap_web_service_key = "PRIVATE_WEB_SECRET_CANARY"
    response = client.get("/api/v1/maps/config", headers=login())
    assert response.json()["js_key"] == "fake-js-public-key"
    assert response.json()["display_enabled"]
    assert "PRIVATE_JS_SECRET_CANARY" not in response.text
    assert "PRIVATE_WEB_SECRET_CANARY" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_style_proxy_is_fixed_and_does_not_accept_business_or_arbitrary_targets(client, settings):
    settings.amap_js_api_key = "fake-js-key"
    settings.amap_js_security_code = "fake-js-secret"
    calls = []

    async def handler(request):
        calls.append(request)
        assert request.url.host == "webapi.amap.com" and request.url.path == "/v4/map/styles"
        assert request.url.params["jscode"] == "fake-js-secret"
        return httpx.Response(200, json={"style": "normal"})

    client.app.state.map_style = MapStyleProxy(settings, transport=httpx.MockTransport(handler))
    path = "/api/v1/maps/_AMapService/v4/map/styles"
    assert client.get(path, params={"key": "fake-js-key", "styleid": "normal"}).status_code == 200
    for arguments in (
        {"key": "fake-js-key", "url": "https://example.com"},
        {"key": "fake-js-key", "jscode": "injected"},
        {"key": "fake-js-key", "callback": "alert(1)"},
        {"key": "wrong"},
    ):
        assert client.get(path, params=arguments).status_code == 400
    assert client.get("/api/v1/maps/_AMapService/v5/place/text?key=fake-js-key").status_code == 404
    assert len(calls) == 1


def test_fixed_style_proxy_supports_binary_styles_with_sdk_metadata(client, settings):
    settings.amap_js_api_key = "fake-js-key"
    settings.amap_js_security_code = "fake-js-secret"

    async def handler(request):
        assert request.url.params["cv"] == "2.0"
        assert request.url.params["jscode"] == "fake-js-secret"
        return httpx.Response(
            200, content=b"\x00style", headers={"content-type": "application/octet-stream"}
        )

    client.app.state.map_style = MapStyleProxy(settings, transport=httpx.MockTransport(handler))
    response = client.get(
        "/api/v1/maps/_AMapService/v4/map/styles",
        params={
            "key": "fake-js-key",
            "cv": "2.0",
            "s": "1",
            "type": "normal",
        },
    )
    assert response.status_code == 200 and response.content == b"\x00style"
