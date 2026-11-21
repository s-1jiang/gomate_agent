from datetime import UTC, datetime

from app.schemas.planning import PlanDraft, TaskSpec, ValidationResult


def validate_draft(task: TaskSpec, plan: PlanDraft) -> ValidationResult:
    """Foundation checks only; opening windows and complete route topology are still pending."""
    errors: list[str] = []
    costs = [stop.cost_fen for stop in plan.stops] + [leg.cost_fen for leg in plan.legs]
    if any(cost is None for cost in costs):
        errors.append("UNKNOWN_COST")
    known_cost = sum(cost for cost in costs if cost is not None)
    if known_cost > task.total_budget_fen:
        errors.append("OVER_BUDGET")
    if plan.return_at > task.end_at:
        errors.append("LATE_RETURN")
    if plan.return_at < plan.stops[-1].departure_at:
        errors.append("INVALID_RETURN_TIME")
    previous = task.start_at
    for stop in plan.stops:
        if stop.arrival_at < previous or stop.departure_at > task.end_at:
            errors.append("INVALID_STOP_WINDOW")
        previous = stop.departure_at
    if not set(task.locked_poi_ids).issubset({stop.poi_id for stop in plan.stops}):
        errors.append("LOCKED_STOP_MISSING")
    return ValidationResult(
        valid=not errors,
        errors=list(dict.fromkeys(errors)),
        total_known_cost_fen=known_cost,
        checked_at=datetime.now(UTC),
    )
