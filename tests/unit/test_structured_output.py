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


@pytest.mark.parametrize(
    "outputs,expected",
    [
        (["blank", "valid"], None),
        (["blank", "blank"], "EMPTY_MODEL_OUTPUT"),
        (["blank", "bad_schema"], "INVALID_AGENT_OUTPUT"),
        (["bad_schema", "blank"], "EMPTY_MODEL_OUTPUT"),
        (["refused", "valid"], "MODEL_REFUSED"),
        (["invalid_provider", "valid"], "INVALID_PROVIDER_RESPONSE"),
    ],
)
def test_empty_recovery_and_schema_correction_share_a_single_extra_call(outputs, expected):
    class Model:
        calls = 0

        async def complete(self, prompt, budget, **kwargs):
            await budget.reserve("llm")
            await budget.reserve("external")
            outcome = outputs[self.calls]
            self.calls += 1
            if self.calls > 1:
                assert "JSON Schema" in prompt[-1].content
                assert all(message.content.strip() for message in prompt)
            if outcome == "blank":
                raise AppError("EMPTY_MODEL_OUTPUT", "empty", 502)
            if outcome == "refused":
                raise AppError("MODEL_REFUSED", "refused", 502)
            if outcome == "invalid_provider":
                raise AppError("INVALID_PROVIDER_RESPONSE", "invalid", 502)
            return '{"keyword":"公园","city":"杭州"}' if outcome == "valid" else "{}"

    model, budget = Model(), RunBudget.create(llm=2)
    operation = structured_complete(
        model, [ChatMessage(role="system", content="Original task")], budget, SearchArguments
    )
    if expected:
        with pytest.raises(AppError) as error:
            asyncio.run(operation)
        assert error.value.code == expected
    else:
        assert asyncio.run(operation).city == "杭州"
    assert model.calls == (1 if outputs[0] in {"refused", "invalid_provider"} else 2)
    assert budget.counts["llm"] == budget.counts["external"] == model.calls


def test_empty_recovery_cannot_reset_the_run_budget():
    class EmptyModel:
        calls = 0

        async def complete(self, prompt, budget, **kwargs):
            await budget.reserve("llm")
            await budget.reserve("external")
            self.calls += 1
            raise AppError("EMPTY_MODEL_OUTPUT", "empty", 502)

    model, budget = EmptyModel(), RunBudget.create(llm=1)
    with pytest.raises(AppError) as error:
        asyncio.run(
            structured_complete(
                model, [ChatMessage(role="user", content="hello")], budget, SearchArguments
            )
        )
    assert error.value.code == "BUDGET_EXCEEDED" and model.calls == 1
