from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    task_version: int = Field(ge=1)
    agent_name: Literal["supervisor", "activity", "dining", "itinerary"]
    status: Literal["completed", "needs_clarification", "failed"]
    evidence_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    task_version: int = 1
    profile_version: int = 0
    agent_results: dict[str, AgentTaskResult] = Field(default_factory=dict)

    def merge_result(self, result: AgentTaskResult) -> None:
        if result.task_version != self.task_version:
            raise ValueError("Stale task result")
        self.agent_results[result.task_id] = result
