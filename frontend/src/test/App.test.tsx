import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { Conversation, Message, Run } from "../api";

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
} = {}) {
  let conversations = [...initial];
  const messages: Message[] = [];
  const sendBodies: { content: string; client_message_id: string }[] = [];
  const calls: { path: string; options?: RequestInit }[] = [];
  const fetchMock = vi.fn(
    async (path: string, options?: RequestInit): Promise<Response> => {
      calls.push({ path, options });
      const method = options?.method || "GET";
      if (path === "/health/ready") return response({ status: "ok" });
      if (path === "/api/v1/me") return response(USER);
      if (path === "/api/v1/auth/register") return response(USER, 201);
      if (path === "/api/v1/auth/login")
        return response({
          access_token: "test-token",
          expires_in: 86400,
          token_type: "bearer",
        });
      if (path === "/api/v1/auth/logout") return response(null, 204);
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
      if (path === "/api/v1/runs/run-1")
        return response({
          ...RUN,
          status: "failed",
          error_code: "WORKFLOW_NOT_IMPLEMENTED",
        });
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
      await screen.findByRole("dialog", { name: "欢迎回到逛搭" }),
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
      screen.getByRole("heading", { name: "把今天，安排得刚刚好。" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /把周末交给自然/ }));
    expect(
      (
        screen.getByRole("textbox", {
          name: "告诉逛搭你的想法",
        }) as HTMLTextAreaElement
      ).value,
    ).toContain("少走路");
    await user.click(screen.getByRole("button", { name: "登录后发送" }));
    expect(
      screen.getByRole("dialog", { name: "欢迎回到逛搭" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.options?.method === "POST")).toBe(false);
  });

  it("registers, signs in, and retains a guest draft without storing the password", async () => {
    const { calls } = backend();
    const user = userEvent.setup();
    render(<App />);
    await user.type(
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
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
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
    ).toHaveValue("周末去逛逛");
    expect(sessionStorage.getItem("gomate.session")).toBe("test-token");
    expect(Object.values(sessionStorage)).not.toContain("test-password-123");
    expect(calls.some((call) => call.path === "/api/v1/auth/register")).toBe(
      true,
    );
  });

  it("persists an idea and shows the actual workflow capability instead of a fabricated itinerary", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    backend();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发送想法" }),
      ).toBeInTheDocument(),
    );
    await user.type(
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
      "下班后想去散步",
    );
    await user.click(screen.getByRole("button", { name: "发送想法" }));
    expect(await screen.findByText("想法已好好收下")).toBeInTheDocument();
    expect(screen.getByText("下班后想去散步")).toBeInTheDocument();
    expect(
      screen.getByText(/完整行程生成功能正在准备中，你可以继续补充/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
    ).toHaveValue("");
  });

  it("reuses the same idempotency key and conversation after a network failure", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { calls, sendBodies } = backend({ failFirstSend: true });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发送想法" }),
      ).toBeInTheDocument(),
    );
    await user.type(
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
      "想找个地方喝咖啡",
    );
    await user.click(screen.getByRole("button", { name: "发送想法" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时连接不上服务",
    );
    expect(
      screen.getByRole("textbox", { name: "告诉逛搭你的想法" }),
    ).toHaveValue("想找个地方喝咖啡");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "发送想法" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "发送想法" }));
    await screen.findByText("想法已好好收下");
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

  it("waits for explicit deletion confirmation and removes only the chosen conversation", async () => {
    sessionStorage.setItem("gomate.session", "test-token");
    const { calls } = backend({ initial: [SESSION] });
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "删除会话：周末的想法" }),
    );
    const dialog = screen.getByRole("dialog", { name: "删除这段会话？" });
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
