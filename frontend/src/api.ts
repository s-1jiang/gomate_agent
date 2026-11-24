export interface User {
  id: string;
  username: string;
  created_at: string;
}
export interface Conversation {
  id: string;
  title: string;
  created_at: string;
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  client_message_id: string | null;
  created_at: string;
  sources?: RetrievalSource[];
  retrieval_status?: "no_matches" | "retrieved" | null;
  map_result?: MapSearchResult | null;
}
export interface WorkflowEvent {
  stage: "route" | "dispatch" | "search" | "review" | "revise" | "complete" | "clarify" | "limit" | "research" | "plan" | "travel" | "validate";
  agent: "supervisor" | "places" | "activity" | "dining" | "itinerary";
  task_id: string | null;
  task_version: number | null;
  summary: string;
}
export interface MapPlace {
  provider: "amap";
  poi_id: string;
  name: string;
  city_code: string;
  city: string;
  district: string;
  address: string;
  category: string;
  location: { longitude: number; latitude: number; coordinate_system: "GCJ02" };
  source_ref: string;
  fetched_at: string;
  label: string;
  task_id: string;
  agent: "places" | "activity" | "dining";
}
export interface MapSearchResult {
  status: "approved" | "no_results" | "revision_limit" | "needs_clarification";
  city: string;
  places: MapPlace[];
  events: WorkflowEvent[];
  review_rounds: number;
  searched_at: string;
  itinerary?: Itinerary | null;
}
export interface ActivityDetail { text: string; evidence_ids: string[]; }
export interface ScheduledStop {
  poi_id: string; name: string; label: string; kind: "visit" | "meal" | "break";
  arrival_at: string; departure_at: string; duration_minutes: number;
  reason: string; activities: ActivityDetail[]; practical_info: ActivityDetail[];
}
export interface ScheduledLeg {
  label: string; origin_poi_id: string; destination_poi_id: string;
  origin_name: string; destination_name: string;
  start_at: string; end_at: string; duration_minutes: number; buffer_minutes: number;
  mode: "walking" | "driving" | "transit"; distance_meters: number; walking_meters: number;
  duration_seconds: number; instructions: string[]; paths: [number, number][][];
  source_ref: string; fetched_at: string;
}
export interface ScheduledDay {
  start_at: string; deadline: string; finish_at: string; spare_minutes: number;
  stops: ScheduledStop[]; legs: ScheduledLeg[];
  total_travel_minutes: number; total_stay_minutes: number; total_walking_meters: number;
}
export interface WebEvidence {
  label: string; poi_id: string; provider: "tavily"; title: string;
  url: string; excerpt: string; fetched_at: string;
}
export interface Itinerary {
  title: string; summary: string; timezone: "Asia/Shanghai";
  request: { days: { start_at: string; end_at: string }[]; origin_name: string;
    return_to_origin: boolean; mode: "walking" | "driving" | "transit";
    party_size: number; budget_fen: number | null; budget_scope: "per_person" | "total";
    assumptions: string[]; requirements: string[]; buffer_minutes: number; max_walking_meters: number | null;
  };
  origin: Omit<MapPlace, "label" | "agent" | "task_id"> | null;
  days: ScheduledDay[]; warnings: string[]; web_sources: WebEvidence[];
  revision_count: number; generated_at: string;
}
export interface MapConfig {
  provider: "amap";
  search_enabled: boolean;
  display_enabled: boolean;
  js_key: string;
  security_proxy: string;
  default_city: string;
  web_search_enabled?: boolean;
}
export interface RetrievalSource {
  label: string;
  cited: boolean;
  available: boolean;
  title?: string | null;
  source_ref?: string | null;
  document_id?: string | null;
  document_version?: number | null;
  chunk_id?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  excerpt?: string | null;
  content_hash?: string | null;
  document_hash?: string | null;
  retrieved_at?: string | null;
  retrieval_method?: "lexical" | null;
  scope?: "session" | "user" | null;
}
export interface KnowledgeDocument {
  id: string;
  title: string;
  source_ref: string;
  scope: "session" | "user";
  session_id: string | null;
  document_version: number;
  content_hash: string;
  chunk_count: number;
  created_at: string;
}
export interface KnowledgeInput {
  title: string;
  source_ref: string;
  content: string;
  scope: "session" | "user";
  session_id: string | null;
}
export interface Run {
  id: string;
  session_id: string;
  message_id: string;
  status:
    | "queued"
    | "running"
    | "waiting_user"
    | "succeeded"
    | "partial"
    | "failed"
    | "cancelled"
    | "timed_out"
    | "interrupted";
  error_code: string | null;
  error_message: string | null;
  tool_calls: number;
  external_requests: number;
  llm_calls: number;
  created_at: string;
  updated_at: string;
  workflow_events?: WorkflowEvent[];
}
export interface Credentials {
  username: string;
  password: string;
}
export interface Token {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(private token: string | null = null) {}

  private async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    headers.set("X-GoMate-Request", "web");
    if (options.body) headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        ...options,
        headers,
        credentials: "same-origin",
        cache: "no-store",
        signal: options.signal
          ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)])
          : AbortSignal.timeout(15000),
      });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError(
        0,
        "CONNECTION_FAILED",
        "无法连接服务，请稍后重试。",
      );
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const code = body?.error?.code || `HTTP_${response.status}`;
      let message = body?.error?.message || "操作未完成，请稍后重试。";
      if (response.status === 422)
        message = path.startsWith("/auth/")
          ? "请检查填写内容；用户名至少 3 位，密码至少 12 位。"
          : "请检查填写内容、长度和资料的可见范围。";
      if (response.status === 429) message = "操作过于频繁，请稍后重试。";
      throw new ApiError(response.status, code, message);
    }
    return response.status === 204
      ? (undefined as T)
      : (response.json() as Promise<T>);
  }

  me(signal?: AbortSignal) {
    return this.request<User>("/me", { signal });
  }
  mapConfig(signal?: AbortSignal) {
    return this.request<MapConfig>("/maps/config", { signal });
  }
  register(body: Credentials) {
    return this.request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
  login(body: Credentials, rememberMe = false) {
    return this.request<Token>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ ...body, remember_me: rememberMe }),
    });
  }
  logout() {
    return this.request<void>("/auth/logout", { method: "POST" });
  }
  conversations(offset = 0, signal?: AbortSignal) {
    return this.request<Conversation[]>(
      `/conversations?limit=100&offset=${offset}`,
      { signal },
    );
  }
  createConversation(title: string) {
    return this.request<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  }
  deleteConversation(id: string) {
    return this.request<void>(`/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }
  messages(id: string, after?: string, signal?: AbortSignal) {
    const cursor = after ? `&after=${encodeURIComponent(after)}` : "";
    return this.request<Message[]>(
      `/conversations/${encodeURIComponent(id)}/messages?limit=100${cursor}`,
      { signal },
    );
  }
  sendMessage(id: string, content: string, clientMessageId: string) {
    return this.request<Run>(
      `/conversations/${encodeURIComponent(id)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content, client_message_id: clientMessageId }),
      },
    );
  }
  run(id: string, signal?: AbortSignal) {
    return this.request<Run>(`/runs/${encodeURIComponent(id)}`, { signal });
  }
  cancelRun(id: string) {
    return this.request<Run>(`/runs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    });
  }
  knowledge(sessionId: string | null, signal?: AbortSignal) {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    return this.request<KnowledgeDocument[]>(`/knowledge/documents${query}`, { signal });
  }
  addKnowledge(body: KnowledgeInput, signal?: AbortSignal) {
    return this.request<KnowledgeDocument>("/knowledge/documents", {
      method: "POST", body: JSON.stringify(body), signal,
    });
  }
  deleteKnowledge(id: string, signal?: AbortSignal) {
    return this.request<void>(`/knowledge/documents/${encodeURIComponent(id)}`, {
      method: "DELETE", signal,
    });
  }
}

const ACTIVE = new Set<Run["status"]>(["queued", "running"]);
export function isActiveRun(run: Run | null): boolean {
  return !!run && ACTIVE.has(run.status);
}
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "操作未完成，请稍后重试。";
}
