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


async def structured_complete(model, prompt, budget, schema):
    messages = list(prompt)
    for attempt in range(2):
        raw = None
        try:
            raw = await model.complete(messages, budget, json_mode=True)
            return structured_reply(raw, schema)
        except AppError as exc:
            if exc.code not in {"EMPTY_MODEL_OUTPUT", "INVALID_AGENT_OUTPUT"} or attempt == 1:
                raise
        # Empty-output recovery and schema correction share ONE extra request, not nested retries.
        # Model.complete reserves the original Run's counters/deadline again for that request.
        messages = [
            *prompt,
            *([ChatMessage(role="assistant", content=raw)] if raw and raw.strip() else []),
            ChatMessage(
                role="user",
                content=(
                    "上一次没有返回可用的 JSON 数据。请直接返回一个完整 JSON 对象，不要只输出空格。"
                    "保持原始需求和已提供的来源，只修正格式与字段，不输出解释。"
                    "必须严格符合以下 JSON Schema：\n"
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                ),
            ),
        ]


@dataclass(frozen=True)
class MapTask:
    id: str
    version: int
    assignment: Assignment
    city: str
    feedback: str = ""
    previous_result: dict | None = None
    fixed_keyword: bool = False


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
                    "keyword 使用简短地点名或地点类别，如西湖、浙江省博物馆、西湖餐厅。"
                    "不要把人数、预算、交通方式、游玩理由拼进地点关键词。"
                    "如果任务指明以已确认地点为中心做周边搜索，keyword 只写类别如餐厅、台球，"
                    "不要再加学校/校区名或‘附近’等限定，中心与半径由程序固定。"
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
        args = (
            SearchArguments(keyword=task.assignment.keyword, city=task.city)
            if task.fixed_keyword
            else await structured_complete(self.model, prompt, budget, SearchArguments)
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
