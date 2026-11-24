import asyncio
import re
import time
from collections import deque

import httpx

from app.core.errors import AppError


class MapStyleProxy:
    """Only the public JS SDK style endpoint, never a general REST or URL proxy."""

    def __init__(self, settings, *, transport=None):
        self.settings, self.transport = settings, transport
        self.requests = deque()
        self.lock, self.semaphore = asyncio.Lock(), asyncio.Semaphore(2)

    async def fetch(self, params):
        key = self.settings.amap_js_api_key
        secret = self.settings.amap_js_security_code.get_secret_value()
        if not key or not secret:
            raise AppError("MAP_DISPLAY_NOT_CONFIGURED", "地图显示需要配置 JS Key 和安全密钥", 503)
        allowed = {
            "key",
            "styleid",
            "protocol",
            "ispublic",
            "output",
            "callback",
            "cb",
            "sdkversion",
            "version",
            "logversion",
            "platform",
            "type",
            "v",
            "cv",
            "s",
            "t",
            "ts",
            "appname",
            "referer",
        }
        pairs = list(params.multi_items())
        if len(pairs) > 15 or len({name for name, _ in pairs}) != len(pairs):
            raise AppError("INVALID_ARGUMENT", "地图样式参数不合法", 400)
        arguments = dict(pairs)
        if arguments.get("key") != key or set(arguments) - allowed:
            raise AppError("INVALID_ARGUMENT", "地图样式参数不合法", 400)
        if any(len(value) > 256 for value in arguments.values()):
            raise AppError("INVALID_ARGUMENT", "地图样式参数过长", 400)
        for callback in (arguments.get("callback"), arguments.get("cb")):
            if callback and not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]{0,100}", callback):
                raise AppError("INVALID_ARGUMENT", "地图样式回调不合法", 400)
        async with self.lock:
            now = time.monotonic()
            while self.requests and self.requests[0] < now - 60:
                self.requests.popleft()
            if len(self.requests) >= 60:
                raise AppError("MAP_RATE_LIMITED", "地图样式请求过于频繁", 429)
            self.requests.append(now)
        arguments["jscode"] = secret
        try:
            async with (
                asyncio.timeout(self.settings.map_timeout_seconds),
                self.semaphore,
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    timeout=self.settings.map_timeout_seconds,
                ) as client,
            ):
                response = await client.get(
                    "https://webapi.amap.com/v4/map/styles", params=arguments
                )
            content = response.content
            content_type = response.headers.get("content-type", "").split(";")[0].lower()
            if (
                response.status_code != 200
                or len(content) > 2_000_000
                or content_type
                not in {
                    "application/json",
                    "application/javascript",
                    "text/javascript",
                    "application/octet-stream",
                    "application/x-protobuf",
                }
                or secret.encode() in content
            ):
                raise AppError("MAP_DISPLAY_UNAVAILABLE", "地图样式暂时不可用", 502)
            return content, content_type
        except (httpx.HTTPError, TimeoutError) as exc:
            raise AppError("MAP_DISPLAY_UNAVAILABLE", "地图样式服务连接失败", 502) from exc
