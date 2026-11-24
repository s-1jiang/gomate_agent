import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.errors import AppError
from app.integrations.contracts import ChatMessage, LanguageModel
from app.schemas.maps import Assignment, SearchArguments
from app.tools.context import ToolContext


def structured_reply(raw: str, schema):
    text = raw.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    try:
        return schema.model_validate_json(text)
    except (ValueError, ValidationError) as exc:
        raise AppError("INVALID_AGENT_OUTPUT", "Agent 返回的任务数据格式不合法", 502) from exc


@dataclass(frozen=True)
class MapTask:
    id: str
    version: int
    assignment: Assignment
    city: str
    feedback: str = ""
    previous_result: dict | None = None


class MapSpecialist:
    def __init__(self, model: LanguageModel, gateway):
        self.model, self.gateway = model, gateway

    async def execute(self, task: MapTask, context: ToolContext, budget):
        prompt = [
            ChatMessage(
                role="system",
                content=(
                    f"你是 {context.agent_name} 地点研究 Agent，只负责自己的任务，"
                    "不能分派其他 Agent。"
                    "根据 Supervisor 的任务和修改反馈制定一次搜索参数。只输出 JSON："
                    '{"keyword":"不超过80字符的单个关键词","city":"指定城市","limit":5}。'
                    "城市必须保持任务城市不变。不得编造地点、坐标、营业或价格，不输出推理过程。"
                ),
            ),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "task_id": task.id,
                        "task_version": task.version,
                        "assignment": task.assignment.model_dump(),
                        "city": task.city,
                        "revision_feedback": task.feedback,
                        "previous_result": task.previous_result,
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
        args = structured_reply(
            await self.model.complete(prompt, budget, json_mode=True), SearchArguments
        )
        if args.city != task.city:
            raise AppError("AGENT_SCOPE_CHANGED", "子 Agent 不能修改任务城市", 502)
        places = await self.gateway.search(context, args, budget)
        return {
            "task_id": task.id,
            "task_version": task.version,
            "agent": context.agent_name,
            "keyword": args.keyword,
            "city": args.city,
            "status": "completed" if places else "no_results",
            "places": [place.model_dump(mode="json") for place in places],
        }
