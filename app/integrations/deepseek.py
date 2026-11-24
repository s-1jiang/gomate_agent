import asyncio
import logging

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.contracts import ChatMessage
from app.tools.budget import RunBudget

logger = logging.getLogger(__name__)


def completion_content(payload) -> str:
    """Validate the provider envelope separately from an Agent's application JSON."""
    if not isinstance(payload, dict):
        raise AppError("INVALID_PROVIDER_RESPONSE", "DeepSeek 接口响应结构异常，请稍后重试", 502)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AppError(
            "INVALID_PROVIDER_RESPONSE", "DeepSeek 接口响应缺少有效回答，请稍后重试", 502
        )
    choice = choices[0]
    reason = choice.get("finish_reason")
    if reason == "length":
        raise AppError("LLM_OUTPUT_TRUNCATED", "回答超过长度限制，请缩小问题范围", 502)
    if reason == "insufficient_system_resource":
        raise AppError("PROVIDER_BUSY", "DeepSeek 服务暂时繁忙，请稍后重新发送", 503)
    if reason == "aborted":
        raise AppError("PROVIDER_GENERATION_ABORTED", "DeepSeek 生成意外中断，请重新发送", 503)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise AppError(
            "INVALID_PROVIDER_RESPONSE", "DeepSeek 接口响应缺少回答字段，请稍后重试", 502
        )
    if reason == "content_filter" or message.get("refusal"):
        raise AppError("MODEL_REFUSED", "DeepSeek 未提供该请求的回答", 502)
    if reason == "tool_calls" or message.get("tool_calls"):
        raise AppError(
            "INVALID_PROVIDER_RESPONSE", "DeepSeek 未返回所需的文字答复，请稍后重试", 502
        )
    if "content" not in message:
        raise AppError(
            "INVALID_PROVIDER_RESPONSE", "DeepSeek 接口响应缺少回答内容，请稍后重试", 502
        )
    content = message.get("content")
    if content is None or (isinstance(content, str) and not content.strip()):
        # JSON mode may replace non-JSON output with spaces, even with finish_reason=stop.
        # reasoning_content is never substituted for the final answer.
        raise AppError("EMPTY_MODEL_OUTPUT", "DeepSeek 返回空内容，请稍后重试", 502)
    if not isinstance(content, str):
        raise AppError("INVALID_PROVIDER_RESPONSE", "DeepSeek 回答字段类型异常，请稍后重试", 502)
    return content


class DeepSeekClient:
    """Non-streaming text adapter used by the conversation service."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def complete(
        self, messages: list[ChatMessage], budget: RunBudget, *, json_mode: bool = False
    ) -> str:
        key = self.settings.deepseek_api_key.get_secret_value()
        if not key:
            raise AppError("PROVIDER_NOT_CONFIGURED", "未配置 DeepSeek API Key", 503)
        await budget.reserve("llm")
        await budget.reserve("external")
        timeout = min(self.settings.llm_timeout_seconds, budget.remaining())
        try:
            async with (
                asyncio.timeout(timeout),
                httpx.AsyncClient(
                    base_url=self.settings.deepseek_base_url.rstrip("/") + "/",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
                    transport=self.transport,
                    follow_redirects=False,
                ) as client,
            ):
                response = await client.post(
                    "chat/completions",
                    json={
                        "model": self.settings.deepseek_model,
                        "thinking": {"type": self.settings.deepseek_thinking},
                        "messages": [message.model_dump() for message in messages],
                        "stream": False,
                        "max_tokens": self.settings.chat_max_output_tokens,
                        **({"response_format": {"type": "json_object"}} if json_mode else {}),
                    },
                )
                if response.status_code in (401, 403):
                    raise AppError("PROVIDER_AUTH_FAILED", "DeepSeek 密钥无效或没有访问权限", 503)
                if response.status_code == 402:
                    raise AppError("PROVIDER_BALANCE_LOW", "DeepSeek 账户余额不足", 503)
                if response.status_code == 400:
                    raise AppError("PROVIDER_BAD_REQUEST", "请检查 DeepSeek 模型和接口配置", 503)
                if response.status_code == 429:
                    raise AppError("PROVIDER_RATE_LIMITED", "DeepSeek 请求限流", 503)
                if not response.is_success:
                    raise AppError("PROVIDER_UNAVAILABLE", "DeepSeek 请求失败", 503)
                try:
                    payload = response.json()
                except ValueError as exc:
                    logger.warning("DeepSeek response rejected: invalid_json_envelope")
                    raise AppError(
                        "INVALID_PROVIDER_RESPONSE", "DeepSeek 接口未返回有效 JSON，请稍后重试", 502
                    ) from exc
                try:
                    content = completion_content(payload)
                except AppError as exc:
                    # Fixed codes only: no response bodies, prompts, credentials or reasoning.
                    logger.warning("DeepSeek response rejected: %s", exc.code)
                    raise
                budget.remaining()  # Discard responses that arrive after cancellation/deadline.
                return content
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError("LLM_TIMEOUT", "DeepSeek 请求超时", 504) from exc
        except httpx.RequestError as exc:
            raise AppError("PROVIDER_UNAVAILABLE", "DeepSeek 暂时不可用", 503) from exc
