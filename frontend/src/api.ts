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
    if (options.body) headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        ...options,
        headers,
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
        "暂时连接不上服务，请稍后重试。",
      );
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const code = body?.error?.code || `HTTP_${response.status}`;
      let message = body?.error?.message || "操作未完成，请稍后重试。";
      if (response.status === 422)
        message = "请检查填写内容；用户名至少 3 位，密码至少 12 位。";
      if (response.status === 429) message = "操作有些频繁，休息一下再试试。";
      throw new ApiError(response.status, code, message);
    }
    return response.status === 204
      ? (undefined as T)
      : (response.json() as Promise<T>);
  }

  me(signal?: AbortSignal) {
    return this.request<User>("/me", { signal });
  }
  register(body: Credentials) {
    return this.request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
  login(body: Credentials) {
    return this.request<Token>("/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
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
}

const ACTIVE = new Set<Run["status"]>(["queued", "running"]);
export function isActiveRun(run: Run | null): boolean {
  return !!run && ACTIVE.has(run.status);
}
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "操作未完成，请稍后重试。";
}
