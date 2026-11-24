import type { WorkflowEvent } from "../api";

export function WorkflowTrace({ events }: { events: WorkflowEvent[] }) {
  if (!events.length) return null;
  return <details className="workflow-trace">
    <summary>任务分发与审查记录</summary>
    <ol>{events.map((event, index) => <li key={index}>
      <strong>{event.agent === "supervisor" ? "Supervisor" : `${event.agent} Agent`}</strong>
      {event.task_version && <small> · 任务版本 {event.task_version}</small>}
      <span>{event.summary}</span>
    </li>)}</ol>
  </details>;
}
