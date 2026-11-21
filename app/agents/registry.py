from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class AgentSpec:
    name: str
    responsibility: str
    allowed_tools: frozenset[str]


AGENTS = MappingProxyType(
    {
        "supervisor": AgentSpec("supervisor", "需求路由、约束汇总、结果协调", frozenset()),
        "activity": AgentSpec(
            "activity",
            "游玩候选及证据研究",
            frozenset(
                {
                    "search_local_places",
                    "get_place_details",
                    "get_weather",
                    "search_private_knowledge",
                }
            ),
        ),
        "dining": AgentSpec(
            "dining",
            "餐饮候选及证据研究",
            frozenset(
                {
                    "search_local_places",
                    "get_place_details",
                    "search_private_knowledge",
                }
            ),
        ),
        "itinerary": AgentSpec(
            "itinerary",
            "路线组合与确定性校验",
            frozenset(
                {
                    "get_route",
                    "build_plan",
                    "validate_plan",
                }
            ),
        ),
    }
)
