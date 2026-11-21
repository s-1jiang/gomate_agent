import asyncio

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.memory.prompt_profile import ActiveProfile
from app.tools.budget import RunBudget
from app.workflows.state import AgentTaskResult, WorkflowState


def test_last_tool_slot_is_reserved_atomically():
    async def scenario():
        budget = RunBudget.create(tool=1)
        results = await asyncio.gather(
            budget.reserve("tool"), budget.reserve("tool"), return_exceptions=True
        )
        assert results.count(None) == 1
        assert sum(isinstance(result, AppError) for result in results) == 1
        assert budget.counts["tool"] == 1

    asyncio.run(scenario())


def test_cancel_and_timeout_stop_dispatch():
    async def scenario():
        budget = RunBudget.create()
        await budget.cancel()
        with pytest.raises(AppError) as exc:
            await budget.reserve("llm")
        assert exc.value.code == "CANCELLED"
        budget = RunBudget.create()
        budget.deadline = 0
        with pytest.raises(AppError) as exc:
            await budget.reserve("external")
        assert exc.value.code == "RUN_TIMEOUT"
        assert budget.counts["external"] == 0

    asyncio.run(scenario())


def test_stale_agent_result_and_uncontrolled_profile_fields_are_rejected():
    state = WorkflowState(run_id="run-1", task_version=2)
    result = AgentTaskResult(
        task_id="task", task_version=1, agent_name="dining", status="completed"
    )
    with pytest.raises(ValueError, match="Stale"):
        state.merge_result(result)
    with pytest.raises(ValidationError):
        ActiveProfile(profile_version=1, user_role="admin")
