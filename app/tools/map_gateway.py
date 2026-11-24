import asyncio

from app.agents.registry import AGENTS
from app.core.errors import AppError
from app.schemas.maps import SearchArguments
from app.tools.budget import RunBudget
from app.tools.context import ToolContext


class MapToolGateway:
    def __init__(self, provider, *, web_provider=None, max_parallel: int = 4, search_center=None):
        self.provider = provider
        self.web_provider = web_provider
        self.semaphore = asyncio.Semaphore(max_parallel)
        self.search_center = search_center

    @staticmethod
    def authorize(context, tool, scope):
        agent = AGENTS.get(context.agent_name)
        if not agent or tool not in agent.allowed_tools or scope not in context.scopes:
            raise AppError("TOOL_FORBIDDEN", "此 Agent 无权调用工具", 403)

    async def route(self, context, *, origin, destination, mode, departure_at, budget):
        await budget.reserve("tool")
        self.authorize(context, "get_route", "map:route")
        async with self.semaphore:
            budget.remaining()
            return await self.provider.get_route(
                origin=origin,
                destination=destination,
                mode=mode,
                departure_at=departure_at,
                budget=budget,
            )

    async def research(self, context, *, place, city, budget):
        await budget.reserve("tool")
        self.authorize(context, "search_web", "web:search")
        async with self.semaphore:
            budget.remaining()
            return await self.web_provider.research(place=place, city=city, budget=budget)

    async def search(self, context: ToolContext, arguments: SearchArguments, budget: RunBudget):
        await budget.reserve("tool")
        agent = AGENTS.get(context.agent_name)
        if not agent or "search_local_places" not in agent.allowed_tools:
            raise AppError("TOOL_FORBIDDEN", "此 Agent 无权调用地点搜索", 403)
        if "map:search" not in context.scopes:
            raise AppError("TOOL_FORBIDDEN", "缺少地图搜索权限", 403)
        async with self.semaphore:
            budget.remaining()
            kwargs = {"center": self.search_center} if self.search_center is not None else {}
            return await self.provider.search_places(
                **arguments.model_dump(), budget=budget, **kwargs
            )
