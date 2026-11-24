import asyncio

from app.agents.registry import AGENTS
from app.core.errors import AppError
from app.schemas.maps import SearchArguments
from app.tools.budget import RunBudget
from app.tools.context import ToolContext


class MapToolGateway:
    def __init__(self, provider, *, max_parallel: int = 4):
        self.provider = provider
        self.semaphore = asyncio.Semaphore(max_parallel)

    async def search(self, context: ToolContext, arguments: SearchArguments, budget: RunBudget):
        await budget.reserve("tool")
        agent = AGENTS.get(context.agent_name)
        if not agent or "search_local_places" not in agent.allowed_tools:
            raise AppError("TOOL_FORBIDDEN", "此 Agent 无权调用地点搜索", 403)
        if "map:search" not in context.scopes:
            raise AppError("TOOL_FORBIDDEN", "缺少地图搜索权限", 403)
        async with self.semaphore:
            budget.remaining()
            return await self.provider.search_places(**arguments.model_dump(), budget=budget)
