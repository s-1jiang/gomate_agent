import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.planning.places import air_distance
from app.schemas.itinerary import RouteObservation
from app.schemas.maps import SearchArguments
from app.schemas.planning import Coordinates, Place
from app.tools.budget import RunBudget

logger = logging.getLogger(__name__)


def text_value(value) -> str:
    return value.strip() if isinstance(value, str) else ""


class AMapClient:
    """Fixed POI endpoint; credentials and upstream addresses never come from an agent."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings, self.transport = settings, transport
        self.request_lock, self.next_request_at = asyncio.Lock(), 0.0

    async def pace(self, budget):
        # Shared by all runs of this client, including parallel research branches.
        async with self.request_lock:
            wait = max(0.0, self.next_request_at - time.monotonic())
            if wait:
                await asyncio.sleep(min(wait, budget.remaining()))
            budget.remaining()
            self.next_request_at = time.monotonic() + self.settings.amap_min_interval_seconds

    async def search_places(
        self, *, keyword: str, city: str, limit: int, budget: RunBudget, center=None
    ):
        args = SearchArguments(keyword=keyword, city=city, limit=limit)
        key = self.settings.amap_web_service_key.get_secret_value()
        if not key:
            raise AppError("MAP_NOT_CONFIGURED", "未配置高德 Web 服务 Key", 503)
        params = {
            "key": key,
            "keywords": args.keyword,
            "region": args.city,
            "city_limit": "true",
            "page_size": args.limit,
            "page_num": 1,
            "output": "json",
        }
        if center is not None:
            if center.location.coordinate_system != "GCJ02":
                raise AppError("INVALID_MAP_ARGUMENT", "周边搜索坐标系无效", 400)
            params.update(
                {
                    "location": f"{center.location.longitude:.6f},{center.location.latitude:.6f}",
                    "radius": 2000,
                    "sortrule": "distance",
                }
            )
        await budget.reserve("external")
        await self.pace(budget)
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
                    "https://restapi.amap.com/v5/place/" + ("around" if center else "text"),
                    params=params,
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
                places, seen, valid_locations = [], set(), 0
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
                    valid_locations += 1
                    if center is not None and air_distance(center.location, coordinates) > 2000:
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
                if pois and not valid_locations:
                    raise AppError("INVALID_MAP_OUTPUT", "高德结果缺少可用的地点或坐标", 502)
                budget.remaining()
                if center is not None:
                    places.sort(key=lambda place: air_distance(center.location, place.location))
                return places
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError("MAP_TIMEOUT", "高德地点查询超时", 504) from exc
        except httpx.HTTPError as exc:
            raise AppError("MAP_UNAVAILABLE", "高德地点服务暂时不可用", 503) from exc
        except (ValueError, TypeError) as exc:
            raise AppError("INVALID_MAP_OUTPUT", "高德返回格式不合法", 502) from exc

    async def get_route(self, *, origin, destination, mode, departure_at, budget):
        endpoints = {"walking": "walking", "driving": "driving", "transit": "transit/integrated"}
        if mode not in endpoints or any(
            place.location.coordinate_system != "GCJ02" for place in (origin, destination)
        ):
            raise AppError("INVALID_ROUTE_ARGUMENT", "路线方式或坐标系不合法", 400)
        key = self.settings.amap_web_service_key.get_secret_value()
        if not key:
            raise AppError("MAP_NOT_CONFIGURED", "未配置高德 Web 服务 Key", 503)
        params = {
            "key": key,
            "origin": f"{origin.location.longitude:.6f},{origin.location.latitude:.6f}",
            "destination": (
                f"{destination.location.longitude:.6f},{destination.location.latitude:.6f}"
            ),
            "show_fields": "cost,polyline",
            "output": "json",
        }
        if mode == "transit":
            if not origin.city_code or not destination.city_code:
                raise AppError("ROUTE_CITY_UNKNOWN", "公交查询缺少地点城市编码", 502)
            params.update(
                {
                    "city1": origin.city_code,
                    "city2": destination.city_code,
                    "date": departure_at.strftime("%Y-%m-%d"),
                    "time": departure_at.strftime("%H-%M"),
                    "AlternativeRoute": "1",
                }
            )
        else:
            params.update({"origin_id": origin.poi_id, "destination_id": destination.poi_id})
        await budget.reserve("external")
        await self.pace(budget)
        timeout = min(self.settings.map_timeout_seconds, budget.remaining())
        try:
            async with (
                asyncio.timeout(timeout),
                httpx.AsyncClient(
                    transport=self.transport, timeout=timeout, follow_redirects=False
                ) as client,
            ):
                response = await client.get(
                    f"https://restapi.amap.com/v5/direction/{endpoints[mode]}", params=params
                )
            if response.status_code == 429:
                raise AppError("ROUTE_RATE_LIMITED", "高德路线查询限流，请稍后重试", 503)
            if response.status_code in {401, 403}:
                raise AppError("ROUTE_AUTH_FAILED", "高德路线查询权限不可用", 503)
            if response.status_code >= 500:
                raise AppError("ROUTE_UNAVAILABLE", "高德路线查询暂时不可用", 503)
            if response.status_code != 200 or len(response.content) > 4000000:
                raise AppError("INVALID_ROUTE_OUTPUT", "高德路线返回无效响应", 502)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid route response")
            if str(payload.get("status")) != "1":
                code = str(payload.get("infocode", ""))
                if len(code) == 5 and code.isascii() and code.isdigit():
                    logger.warning("AMap route rejected: infocode=%s", code)
                if code in {
                    "10003",
                    "10004",
                    "10010",
                    "10014",
                    "10015",
                    "10019",
                    "10020",
                    "10021",
                    "10029",
                    "10044",
                    "10045",
                    "40000",
                    "40003",
                }:
                    raise AppError(
                        "ROUTE_RATE_LIMITED", "高德路线查询限流或配额不足，请稍后重试", 503
                    )
                if code in {
                    "10001",
                    "10002",
                    "10005",
                    "10006",
                    "10007",
                    "10008",
                    "10009",
                    "10012",
                    "10013",
                    "10026",
                    "10041",
                    "20011",
                    "40002",
                }:
                    raise AppError("ROUTE_AUTH_FAILED", "高德路线查询权限不可用", 503)
                if code in {"20800", "20801", "20802", "20803"}:
                    raise AppError("ROUTE_NOT_FOUND", "未查到可通行的路线", 422)
                if code in {"20000", "20001", "20002", "20012"}:
                    raise AppError("INVALID_ROUTE_ARGUMENT", "高德路线请求参数无效", 502)
                raise AppError("ROUTE_UNAVAILABLE", "高德路线查询暂时不可用", 503)
            route = payload.get("route")
            if not isinstance(route, dict):
                raise ValueError("Missing route object")
            rows = route.get("transits" if mode == "transit" else "paths")
            if not isinstance(rows, list):
                raise ValueError("Missing route list")
            if not rows:
                raise AppError("ROUTE_NOT_FOUND", "两地间没有查到所选交通方式的路线", 422)
            row = rows[0]
            if not isinstance(row, dict):
                raise ValueError("Invalid route row")
            distance = int(float(row["distance"]))
            duration = int(float(row["cost"]["duration"]))
            instructions, points, paths = [], [], []
            walking = distance if mode == "walking" else 0

            def add_steps(steps):
                for step in steps[:200] if isinstance(steps, list) else []:
                    if not isinstance(step, dict):
                        continue
                    instruction = text_value(step.get("instruction"))
                    if instruction and len(instructions) < 8:
                        instructions.append(instruction[:200])
                    segment_points = []
                    for pair in text_value(step.get("polyline")).split(";")[:2000]:
                        try:
                            lon, lat = (float(value) for value in pair.split(","))
                            point = Coordinates(
                                longitude=lon, latitude=lat, coordinate_system="GCJ02"
                            )
                        except (ValueError, ValidationError):
                            continue
                        if len(points) < 2000:
                            points.append((point.longitude, point.latitude))
                            segment_points.append((point.longitude, point.latitude))
                    if len(segment_points) > 1:
                        paths.append(segment_points)

            if mode == "transit":
                for segment in row.get("segments", [])[:100]:
                    walk = segment.get("walking") or {}
                    walking += int(float(walk.get("distance") or 0))
                    add_steps(walk.get("steps", []))
                    for line in (segment.get("bus") or {}).get("buslines", [])[:4]:
                        name = text_value(line.get("name"))
                        if name and len(instructions) < 8:
                            instructions.append(name[:200])
                        add_steps([{"polyline": line.get("polyline")}])
            else:
                add_steps(row.get("steps", []))
            budget.remaining()
            return RouteObservation(
                origin_poi_id=origin.poi_id,
                destination_poi_id=destination.poi_id,
                mode=mode,
                distance_meters=distance,
                walking_meters=walking,
                duration_seconds=duration,
                instructions=instructions,
                paths=paths,
                source_ref=f"amap:route:{mode}:{origin.poi_id}:{destination.poi_id}",
                fetched_at=datetime.now(UTC),
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError("ROUTE_TIMEOUT", "路线查询超时", 504) from exc
        except httpx.HTTPError as exc:
            raise AppError("ROUTE_UNAVAILABLE", "路线查询连接失败", 503) from exc
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise AppError("INVALID_ROUTE_OUTPUT", "高德路线结果缺少有效的耗时或距离", 502) from exc
