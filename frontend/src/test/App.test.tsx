import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { Conversation, Message, RetrievalSource, Run } from "../api";

const USER = {
  id: "user-a",
  username: "tester",
  created_at: "2026-11-21T00:00:00Z",
};
const SESSION: Conversation = {
  id: "session-1",
  title: "周末的想法",
  created_at: "2026-11-21T00:00:00Z",
};
const RUN: Run = {
  id: "run-1",
  session_id: SESSION.id,
  message_id: "message-1",
  status: "queued",
  tool_calls: 0,
  external_requests: 0,
  llm_calls: 0,
  error_code: null,
  error_message: null,
  created_at: "2026-11-21T00:00:01Z",
  updated_at: "2026-11-21T00:00:01Z",
};

function response(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function backend({
  initial = [] as Conversation[],
  failFirstSend = false,
  replyText = "可以先从附近的公园开始。",
  replySources = [] as RetrievalSource[],
  runFailure = null as { code: string; message: string } | null,
  cookieSession = false,
} = {}) {
  let signedInCookie = cookieSession;
  let conversations = [...initial];
  const messages: Message[] = [];
  const sendBodies: { content: string; client_message_id: string }[] = [];
  const calls: { path: string; options?: RequestInit }[] = [];
  const fetchMock = vi.fn(
    async (path: string, options?: RequestInit): Promise<Response> => {
      calls.push({ path, options });
      const method = options?.method || "GET";
      if (path === "/health/ready") return response({ status: "ok" });
      if (path === "/api/v1/me") {
        if (!signedInCookie && !new Headers(options?.headers).has("Authorization"))
          return response({ error: { code: "UNAUTHORIZED", message: "请先登录" } }, 401);
        return response(USER);
      }
      if (path === "/api/v1/auth/register") return response(USER, 201);
      if (path === "/api/v1/auth/login") {
        signedInCookie = JSON.parse(String(options?.body)).remember_me === true;
        return response({
          access_token: "test-token",
          expires_in: 86400,
          token_type: "bearer",
        });
      }
      if (path === "/api/v1/auth/logout") { signedInCookie = false; return response(null, 204); }
      if (path.startsWith("/api/v1/conversations?"))
        return response(conversations);
      if (path === "/api/v1/conversations" && method === "POST") {
        conversations = [SESSION, ...conversations];
        return response(SESSION, 201);
      }
      if (path.endsWith("/messages") && method === "POST") {
        const body = JSON.parse(String(options?.body));
        sendBodies.push(body);
        if (failFirstSend && sendBodies.length === 1)
          throw new TypeError("Network lost after submission");
        messages.push({
          id: RUN.message_id,
          role: "user",
          content: body.content,
          client_message_id: body.client_message_id,
          created_at: RUN.created_at,
        });
        return response(RUN, 202);
      }
      if (path.includes("/messages?")) return response(messages);
      if (path === "/api/v1/runs/run-1") {
        if (!runFailure && !messages.some((item) => item.id === "reply-1")) {
          messages.push({
            id: "reply-1", role: "assistant", content: replyText,
            client_message_id: null, created_at: "2026-11-21T00:00:02Z",
            sources: replySources, retrieval_status: replySources.length ? "retrieved" : "no_matches",
          });
        }
        return response({ ...RUN, status: runFailure ? "failed" : "succeeded",
          error_code: runFailure?.code || null, error_message: runFailure?.message || null });
      }
      if (path.startsWith("/api/v1/conversations/") && method === "DELETE") {
        conversations = conversations.filter((item) => !path.endsWith(item.id));
        return response(null, 204);
      }
      throw new Error(`Unmocked request: ${method} ${path}`);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls, sendBodies };
}

beforeEach(() => {
  sessionStorage.clear();
});

describe("GoMate workspace", () => {
  it("clears expired login state and asks for authentication again", async () => {
    sessionStorage.setItem("gomate.session", "expired-token");
    const { fetchMock } = backend();
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/v1/me")
        return Promise.resolve(
          response(
            {
              error: {
                code: "UNAUTHORIZED",
                message: "请重新登录",
              },
            },
            401,
          ),
        );
      return original(path, options);
    });
    render(<App />);
    expect(
      await screen.findByRole("dialog", { name: "登录逛搭" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("登录已过期");
    expect(sessionStorage.getItem("gomate.session")).toBeNull();
  });

  it("discards an old account's delayed history after logout and another login", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { fetchMock } = backend();
    const original = fetchMock.getMockImplementation()!;
    let firstList = true;
    let nextAccount = false;
    let release: (value: Response) => void = () => {};
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/v1/conversations?") && firstList) {
        firstList = false;
        return new Promise((resolve) => {
          release = resolve;
        });
      }
      if (path === "/api/v1/me" && nextAccount)
        return Promise.resolve(
          response({
            ...USER,
            id: "user-b",
            username: "another_user",
          }),
        );
      return original(path, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "退出登录" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument(),
    );
    await act(async () => {
      release(response([SESSION]));
    });
    nextAccount = true;
    await user.click(screen.getByRole("button", { name: "登录" }));
    await user.type(screen.getByLabelText("用户名"), "another_user");
    await user.type(
      screen.getByLabelText("密码", { exact: true }),
      "another-password-123",
    );
    await user.click(screen.getByRole("button", { name: "登录逛搭" }));
    await screen.findByText("another_user");
    expect(
      screen.queryByRole("button", { name: "打开会话：周末的想法" }),
    ).not.toBeInTheDocument();
  });

  it("keeps guest ideas in the composer and asks for login before saving", async () => {
    const { calls } = backend();
    const user = userEvent.setup();
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "描述你的出行需求" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /周末半日游/ }));
    expect(
      (
        screen.getByRole("textbox", {
          name: "输入出行需求",
        }) as HTMLTextAreaElement
      ).value,
    ).toContain("少走路");
    await user.click(screen.getByRole("button", { name: "登录后发送" }));
    expect(
      screen.getByRole("dialog", { name: "登录逛搭" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.options?.method === "POST")).toBe(false);
  });

  it("registers, signs in, and retains a guest draft without storing the password", async () => {
    const { calls } = backend();
    const user = userEvent.setup();
    render(<App />);
    await user.type(
      screen.getByRole("textbox", { name: "输入出行需求" }),
      "周末去逛逛",
    );
    await user.click(screen.getByRole("button", { name: "登录" }));
    await user.click(screen.getByRole("tab", { name: "注册账号" }));
    await user.type(screen.getByLabelText("用户名"), "tester");
    await user.type(
      screen.getByLabelText("密码", { exact: true }),
      "test-password-123",
    );
    await user.click(screen.getByRole("button", { name: "创建账号并登录" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("textbox", { name: "输入出行需求" }),
    ).toHaveValue("周末去逛逛");
    expect(sessionStorage.getItem("gomate.session")).toBeNull();
    expect(localStorage.getItem("gomate.rememberedUsername")).toBe("tester");
    expect(Object.values(sessionStorage)).not.toContain("test-password-123");
    expect(Object.values(localStorage)).not.toContain("test-password-123");
    expect(calls.some((call) => call.path === "/api/v1/auth/register")).toBe(
      true,
    );
  });

  it("restores the persistent browser session after reopening without saving a password or token in web storage", async () => {
    const { calls } = backend({ cookieSession: true });
    const first = render(<App />);
    await screen.findByText("tester");
    first.unmount();
    sessionStorage.clear();
    render(<App />);
    await screen.findByText("tester");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/api/v1/me").length).toBeGreaterThanOrEqual(2);
    expect(calls.some((call) => call.path === "/api/v1/auth/login")).toBe(false);
    expect(sessionStorage.getItem("gomate.session")).toBeNull();
    expect(localStorage.getItem("gomate.session")).toBeNull();
    const restore = calls.filter((call) => call.path === "/api/v1/me").at(-1)!;
    expect(restore.options?.credentials).toBe("same-origin");
    expect(new Headers(restore.options?.headers).has("Authorization")).toBe(false);
  });

  it("uses a tab session when keep-login is unchecked and forgets it on a new browser session", async () => {
    const { calls } = backend();
    const user = userEvent.setup();
    const first = render(<App />);
    await user.click(await screen.findByRole("button", { name: "登录" }));
    expect(screen.getByRole("checkbox", { name: "保持登录" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "保持登录" }));
    await user.click(screen.getByRole("checkbox", { name: "记住账号密码" }));
    await user.type(screen.getByLabelText("用户名"), "tester");
    await user.type(screen.getByLabelText("密码", { exact: true }), "test-password-123");
    await user.click(screen.getByRole("button", { name: "登录逛搭" }));
    await screen.findByText("tester");
    expect(sessionStorage.getItem("gomate.session")).toBe("test-token");
    expect(localStorage.getItem("gomate.rememberedUsername")).toBeNull();
    const login = calls.find((call) => call.path === "/api/v1/auth/login")!;
    expect(JSON.parse(String(login.options?.body)).remember_me).toBe(false);
    first.unmount();
    sessionStorage.clear();
    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeEnabled());
    expect(screen.queryByText("tester")).not.toBeInTheDocument();
  });

  it("prefills a remembered username and revokes persistent login on explicit logout", async () => {
    localStorage.setItem("gomate.rememberedUsername", "tester");
    const { calls } = backend();
    const user = userEvent.setup();
    const first = render(<App />);
    await user.click(await screen.findByRole("button", { name: "登录" }));
    expect(screen.getByLabelText("用户名")).toHaveValue("tester");
    expect(screen.getByLabelText("密码", { exact: true })).toHaveAttribute("autocomplete", "current-password");
    await user.type(screen.getByLabelText("密码", { exact: true }), "test-password-123");
    await user.click(screen.getByRole("button", { name: "登录逛搭" }));
    await screen.findByText("tester");
    expect(JSON.parse(String(calls.find((call) => call.path === "/api/v1/auth/login")?.options?.body)).remember_me).toBe(true);
    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeEnabled());
    first.unmount();
    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeEnabled());
    expect(screen.queryByText("tester")).not.toBeInTheDocument();
    expect(localStorage.getItem("gomate.rememberedUsername")).toBe("tester");
  });

  it("reports a failed logout and preserves the authenticated view until the server can revoke it", async () => {
    const { fetchMock } = backend({ cookieSession: true });
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/v1/auth/logout") return Promise.reject(new TypeError("Network down"));
      return original(path, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "退出登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("退出登录未完成");
    expect(screen.getByText("tester")).toBeInTheDocument();
  });

  it("loads the assistant answer after completion and identifies replies with no retrieved evidence", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    backend();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发送消息" }),
      ).toBeInTheDocument(),
    );
    await user.type(
      screen.getByRole("textbox", { name: "输入出行需求" }),
      "下班后想去散步",
    );
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("回复已完成")).toBeInTheDocument();
    expect(screen.getByText("下班后想去散步")).toBeInTheDocument();
    expect(
      await screen.findByText("可以先从附近的公园开始。"),
    ).toBeInTheDocument();
    expect(screen.getByText("未检索到相关资料，本次回复由模型生成。")).toBeInTheDocument();
    expect(screen.queryByLabelText("检索来源")).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "输入出行需求" }),
    ).toHaveValue("");
  });

  it("reuses the same idempotency key and conversation after a network failure", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { calls, sendBodies } = backend({ failFirstSend: true });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发送消息" }),
      ).toBeInTheDocument(),
    );
    await user.type(
      screen.getByRole("textbox", { name: "输入出行需求" }),
      "想找个地方喝咖啡",
    );
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "无法连接服务",
    );
    expect(
      screen.getByRole("textbox", { name: "输入出行需求" }),
    ).toHaveValue("想找个地方喝咖啡");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "发送消息" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByText("回复已完成");
    expect(sendBodies).toHaveLength(2);
    expect(sendBodies[0].client_message_id).toBe(
      sendBodies[1].client_message_id,
    );
    expect(
      calls.filter(
        (call) =>
          call.path === "/api/v1/conversations" &&
          call.options?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("shows server-provided evidence, original excerpt and the distinction between retrieval and citation", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const source: RetrievalSource = {
      label: "R1", cited: true, available: true, title: "周末笔记",
      source_ref: "周末笔记.md", document_id: "document-1", document_version: 1,
      chunk_id: "chunk-1", start_line: 2, end_line: 4, excerpt: "公园沿河，适合散步。",
      content_hash: "test-content-hash", document_hash: "test-document-hash",
      retrieval_method: "lexical", scope: "session", retrieved_at: RUN.created_at,
    };
    backend({ replyText: "可以去河边公园。[R1]", replySources: [source, {
      ...source, label: "R2", cited: false, title: "另一个召回片段",
    }] });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("tester");
    await user.type(screen.getByRole("textbox", { name: "输入出行需求" }), "周末散步");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByText("可以去河边公园。[R1]");
    const sources = screen.getByRole("region", { name: "检索来源" });
    expect(within(sources).getByText("正文已引用")).toBeInTheDocument();
    expect(within(sources).getByText("已召回，正文未引用")).toBeInTheDocument();
    await user.click(within(sources).getByText("周末笔记"));
    const first = within(sources.querySelector("details")!);
    expect(first.getByText("公园沿河，适合散步。")).toBeVisible();
    expect(first.getByText(/周末笔记.md · 第 2–4 行 · 版本 1/)).toBeVisible();
    expect(first.getByText("test-content-hash")).toBeVisible();
  });

  it("shows provider failures without inventing an assistant answer", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    backend({ runFailure: { code: "PROVIDER_AUTH_FAILED", message: "DeepSeek 密钥无效或没有访问权限" } });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("tester");
    await user.type(screen.getByRole("textbox", { name: "输入出行需求" }), "你好");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("DeepSeek 密钥无效或没有访问权限")).toBeInTheDocument();
    expect(screen.queryByText("可以先从附近的公园开始。")).not.toBeInTheDocument();
  });

  it("imports text into the chosen knowledge scope and confirms deletion", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { fetchMock, calls } = backend();
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/v1/knowledge/documents")) {
        calls.push({ path, options });
        if (options?.method === "POST") {
          const body = JSON.parse(String(options.body));
          return Promise.resolve(response({ ...body, id: "doc-1", document_version: 1,
            chunk_count: 1, content_hash: "hash", created_at: RUN.created_at }, 201));
        }
        return Promise.resolve(response(options?.method === "DELETE" ? null : [], options?.method === "DELETE" ? 204 : 200));
      }
      return original(path, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("tester");
    await user.click(screen.getByRole("button", { name: "知识库" }));
    const dialog = screen.getByRole("dialog", { name: "知识库" });
    await user.type(within(dialog).getByLabelText("资料名称"), "散步笔记");
    await user.type(within(dialog).getByLabelText("来源说明"), "walk.md");
    await user.type(within(dialog).getByLabelText("资料正文"), "河边适合散步。");
    await user.click(within(dialog).getByRole("button", { name: "加入知识库" }));
    await within(dialog).findByText("资料已加入，可在后续对话中检索。");
    const saved = calls.find((call) => call.path === "/api/v1/knowledge/documents" && call.options?.method === "POST");
    expect(JSON.parse(String(saved?.options?.body))).toMatchObject({
      scope: "user", session_id: null, source_ref: "walk.md", content: "河边适合散步。",
    });
    await user.click(within(dialog).getByRole("button", { name: "删除资料：散步笔记" }));
    expect(calls.some((call) => call.options?.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "确认删除资料" }));
    await within(dialog).findByText("资料已删除，不再参与检索。");
    expect(within(dialog).queryByText("散步笔记")).not.toBeInTheDocument();
  });

  it("waits for explicit deletion confirmation and removes only the chosen conversation", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { calls } = backend({ initial: [SESSION] });
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "删除会话：周末的想法" }),
    );
    const dialog = screen.getByRole("dialog", { name: "删除会话？" });
    expect(calls.some((call) => call.options?.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "保留会话" }));
    expect(calls.some((call) => call.options?.method === "DELETE")).toBe(false);
    await user.click(
      screen.getByRole("button", { name: "删除会话：周末的想法" }),
    );
    await user.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "删除会话：周末的想法" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      calls
        .filter((call) => call.options?.method === "DELETE")
        .map((call) => call.path),
    ).toEqual(["/api/v1/conversations/session-1"]);
  });

  it("does not display a late response from the previous conversation", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const second = { ...SESSION, id: "session-2", title: "今天的小计划" };
    const { fetchMock } = backend({ initial: [SESSION, second] });
    const original = fetchMock.getMockImplementation()!;
    let release: (value: Response) => void = () => {};
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path.includes("/session-1/messages?"))
        return new Promise((resolve) => {
          release = resolve;
        });
      if (path.includes("/session-2/messages?"))
        return Promise.resolve(
          response([
            {
              id: "two",
              role: "user",
              content: "CURRENT_SESSION",
              client_message_id: "two",
              created_at: RUN.created_at,
            },
          ]),
        );
      return original(path, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "打开会话：周末的想法" }),
    );
    await user.click(
      screen.getByRole("button", { name: "打开会话：今天的小计划" }),
    );
    await screen.findByText("CURRENT_SESSION");
    await act(async () => {
      release(
        response([
          {
            id: "one",
            role: "user",
            content: "OLD_SESSION_CANARY",
            client_message_id: "one",
            created_at: RUN.created_at,
          },
        ]),
      );
    });
    expect(screen.queryByText("OLD_SESSION_CANARY")).not.toBeInTheDocument();
    expect(screen.getByText("CURRENT_SESSION")).toBeInTheDocument();
  });
});
