import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

from app.core.errors import AppError

BudgetKind = Literal["tool", "external", "llm"]


@dataclass
class RunBudget:
    """Shared by all tasks in ONE process. Durable gateway accounting is a later phase."""

    deadline: float
    limits: dict[BudgetKind, int]
    counts: dict[BudgetKind, int] = field(
        default_factory=lambda: {"tool": 0, "external": 0, "llm": 0}
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _cancelled: bool = field(default=False, init=False, repr=False)

    @classmethod
    def create(cls, *, timeout: float = 120, tool: int = 16, external: int = 32, llm: int = 12):
        if timeout <= 0 or min(tool, external, llm) < 0:
            raise ValueError("Budget limits must be non-negative and timeout must be positive")
        return cls(time.monotonic() + timeout, {"tool": tool, "external": external, "llm": llm})

    def remaining(self) -> float:
        if self._cancelled:
            raise AppError("CANCELLED", "任务已取消", 409)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AppError("RUN_TIMEOUT", "任务已超时", 408)
        return remaining

    async def reserve(self, kind: BudgetKind) -> None:
        async with self._lock:
            self.remaining()
            if self.counts[kind] >= self.limits[kind]:
                raise AppError("BUDGET_EXCEEDED", f"{kind} 调用次数已达上限", 429)
            self.counts[kind] += 1

    async def cancel(self) -> None:
        async with self._lock:
            self._cancelled = True
