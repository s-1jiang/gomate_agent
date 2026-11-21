import asyncio

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.contracts import ChatMessage
from app.tools.budget import RunBudget


class DeepSeekClient:
    """Text-completion adapter. Not yet wired into a planning or tool-calling workflow."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def complete(self, messages: list[ChatMessage], budget: RunBudget) -> str:
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
                        "messages": [message.model_dump() for message in messages],
                        "stream": False,
                    },
                )
                if response.status_code == 429:
                    raise AppError("PROVIDER_RATE_LIMITED", "DeepSeek 请求限流", 503)
                if not response.is_success:
                    raise AppError("PROVIDER_UNAVAILABLE", "DeepSeek 请求失败", 503)
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Missing text content")
                budget.remaining()  # Discard responses that arrive after cancellation/deadline.
                return content
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError("LLM_TIMEOUT", "DeepSeek 请求超时", 504) from exc
        except httpx.RequestError as exc:
            raise AppError("PROVIDER_UNAVAILABLE", "DeepSeek 暂时不可用", 503) from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AppError("INVALID_MODEL_OUTPUT", "DeepSeek 返回格式不合法", 502) from exc
