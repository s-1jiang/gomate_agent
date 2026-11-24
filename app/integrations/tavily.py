import asyncio
import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.core.errors import AppError
from app.schemas.itinerary import WebEvidence


def public_source_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return False
        host = parts.hostname.lower()
        if host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class TavilyClient:
    def __init__(self, settings, *, transport=None):
        self.settings, self.transport = settings, transport

    async def research(self, *, place, city, budget):
        key = self.settings.tavily_api_key.get_secret_value()
        if not key:
            return []
        await budget.reserve("external")
        timeout = min(self.settings.web_search_timeout_seconds, budget.remaining())
        try:
            async with (
                asyncio.timeout(timeout),
                httpx.AsyncClient(
                    transport=self.transport, follow_redirects=False, timeout=timeout
                ) as client,
            ):
                response = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        # Send only public place research terms, never conversation/private RAG.
                        "query": f"{city} {place.name} 游玩看点 开放时间 预约 官方",
                        "topic": "general",
                        "search_depth": "basic",
                        "max_results": 3,
                        "include_answer": False,
                        "include_raw_content": False,
                        "include_images": False,
                    },
                )
            if response.status_code in (401, 403):
                raise AppError("WEB_AUTH_FAILED", "Tavily 鉴权失败，请检查 Key", 503)
            if response.status_code in (429, 432, 433):
                raise AppError("WEB_RATE_LIMITED", "联网搜索额度不足或限流", 503)
            if response.status_code != 200 or len(response.content) > 1000000:
                raise AppError("WEB_UNAVAILABLE", "联网搜索暂时不可用", 503)
            rows = response.json()["results"]
            if not isinstance(rows, list):
                raise ValueError("Invalid search response")
            sources, seen = [], set()
            for row in rows[:3]:
                if not isinstance(row, dict):
                    continue
                url, text = row.get("url"), row.get("content")
                if not public_source_url(url) or url in seen or not isinstance(text, str):
                    continue
                seen.add(url)
                sources.append(
                    WebEvidence(
                        label="",
                        poi_id=place.poi_id,
                        title=str(row.get("title", "网页资料"))[:200],
                        url=url,
                        excerpt=text[:1200],
                        fetched_at=datetime.now(UTC),
                    )
                )
            budget.remaining()
            return sources
        except (httpx.HTTPError, TimeoutError) as exc:
            raise AppError("WEB_UNAVAILABLE", "联网搜索超时或连接失败", 503) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError("INVALID_WEB_OUTPUT", "联网检索返回格式不合法", 502) from exc
