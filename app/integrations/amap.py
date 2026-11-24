import asyncio
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.maps import SearchArguments
from app.schemas.planning import Coordinates, Place
from app.tools.budget import RunBudget


def text_value(value) -> str:
    return value.strip() if isinstance(value, str) else ""


class AMapClient:
    """Fixed POI endpoint; credentials and upstream addresses never come from an agent."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings, self.transport = settings, transport

    async def search_places(self, *, keyword: str, city: str, limit: int, budget: RunBudget):
        args = SearchArguments(keyword=keyword, city=city, limit=limit)
        key = self.settings.amap_web_service_key.get_secret_value()
        if not key:
            raise AppError("MAP_NOT_CONFIGURED", "未配置高德 Web 服务 Key", 503)
        await budget.reserve("external")
        timeout = min(self.settings.map_timeout_seconds, budget.remaining())
        try:
            async with (
                asyncio.timeout(timeout),
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    timeout=timeout,
                ) as client,
            ):
                response = await client.get(
                    "https://restapi.amap.com/v5/place/text",
                    params={
                        "key": key,
                        "keywords": args.keyword,
                        "region": args.city,
                        "city_limit": "true",
                        "page_size": args.limit,
                        "page_num": 1,
                        "output": "json",
                    },
                )
                if response.status_code == 429:
                    raise AppError("MAP_RATE_LIMITED", "高德请求限流，请稍后重试", 503)
                if response.status_code != 200:
                    raise AppError("MAP_UNAVAILABLE", "高德地点服务暂时不可用", 503)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid response")
                if str(payload.get("status")) != "1":
                    code = str(payload.get("infocode", ""))
                    if code in {"10001", "10005", "10006", "10007", "10009", "10012", "10013"}:
                        raise AppError(
                            "MAP_AUTH_FAILED", "请检查高德 Key 类型、权限和访问限制", 503
                        )
                    if code in {"10003", "10004", "10010", "10019", "10020", "10021", "10044"}:
                        raise AppError("MAP_RATE_LIMITED", "高德配额不足或请求限流", 503)
                    raise AppError("MAP_UNAVAILABLE", "高德地点查询失败", 503)
                pois = payload.get("pois")
                if not isinstance(pois, list):
                    raise ValueError("Missing POI list")
                places, seen = [], set()
                fetched = datetime.now(UTC)
                for item in pois[: args.limit]:
                    if not isinstance(item, dict):
                        continue
                    poi_id, name = text_value(item.get("id")), text_value(item.get("name"))
                    location = text_value(item.get("location"))
                    if not poi_id or not name or poi_id in seen or len(poi_id) > 80:
                        continue
                    try:
                        longitude, latitude = (float(value) for value in location.split(","))
                        coordinates = Coordinates(
                            longitude=longitude, latitude=latitude, coordinate_system="GCJ02"
                        )
                    except (ValueError, ValidationError):
                        continue
                    seen.add(poi_id)
                    places.append(
                        Place(
                            poi_id=poi_id,
                            name=name[:200],
                            city_code=text_value(item.get("citycode")),
                            location=coordinates,
                            source_ref=f"amap:poi:{poi_id}",
                            fetched_at=fetched,
                            address=text_value(item.get("address"))[:500],
                            city=text_value(item.get("cityname"))[:80],
                            district=text_value(item.get("adname"))[:80],
                            category=text_value(item.get("type"))[:200],
                        )
                    )
                if pois and not places:
                    raise AppError("INVALID_MAP_OUTPUT", "高德结果缺少可用的地点或坐标", 502)
                budget.remaining()
                return places
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError("MAP_TIMEOUT", "高德地点查询超时", 504) from exc
        except httpx.HTTPError as exc:
            raise AppError("MAP_UNAVAILABLE", "高德地点服务暂时不可用", 503) from exc
        except (ValueError, TypeError) as exc:
            raise AppError("INVALID_MAP_OUTPUT", "高德返回格式不合法", 502) from exc
