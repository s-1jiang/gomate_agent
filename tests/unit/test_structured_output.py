import asyncio

import pytest

from app.agents.map_specialist import structured_complete
from app.core.errors import AppError
from app.integrations.contracts import ChatMessage
from app.schemas.maps import SearchArguments
from app.tools.budget import RunBudget


@pytest.mark.parametrize("repair", [True, False])
def test_schema_correction_is_bounded_and_keeps_shared_budget(repair):
    class Model:
        calls = 0

        async def complete(self, prompt, budget, **kwargs):
            await budget.reserve("llm")
            await budget.reserve("external")
            self.calls += 1
            if self.calls > 1:
                assert "JSON Schema" in prompt[-1].content
                assert prompt[0].content == "Original task"
            return '{"keyword":"公园","city":"杭州"}' if self.calls == 2 and repair else "{}"

    model, budget = Model(), RunBudget.create(llm=2)
    operation = structured_complete(
        model, [ChatMessage(role="system", content="Original task")], budget, SearchArguments
    )
    if repair:
        assert asyncio.run(operation).keyword == "公园"
    else:
        with pytest.raises(AppError) as error:
            asyncio.run(operation)
        assert error.value.code == "INVALID_AGENT_OUTPUT"
    assert model.calls == 2 and budget.counts["llm"] == budget.counts["external"] == 2
