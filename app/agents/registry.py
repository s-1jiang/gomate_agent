from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class AgentSpec:
    name: str
    responsibility: str
    allowed_tools: frozenset[str]


AGENTS = MappingProxyType(
    {
        "supervisor": AgentSpec("supervisor", "任务分发、结果审查与定向返工", frozenset()),
        "places": AgentSpec("places", "通用地点搜索与来源核实", frozenset({"search_local_places"})),
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
