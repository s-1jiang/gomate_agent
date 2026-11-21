import { expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../api";

it("sends bearer credentials only in headers and encodes resource IDs", async () => {
  const request = vi
    .fn()
    .mockResolvedValue(new Response("[]", { status: 200 }));
  vi.stubGlobal("fetch", request);
  await new ApiClient("private-token").messages("session/a?x=1");
  const [url, options] = request.mock.calls[0];
  expect(url).toBe(
    "/api/v1/conversations/session%2Fa%3Fx%3D1/messages?limit=100",
  );
  expect(url).not.toContain("private-token");
  expect(new Headers(options.headers).get("Authorization")).toBe(
    "Bearer private-token",
  );
});

it("preserves server error codes and keeps provider text out of generic network failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "IDEMPOTENCY_CONFLICT",
            message: "同一消息标识不能提交不同内容",
          },
        }),
        { status: 409 },
      ),
    ),
  );
  await expect(
    new ApiClient("token").sendMessage("session", "different", "key"),
  ).rejects.toMatchObject({ status: 409, code: "IDEMPOTENCY_CONFLICT" });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("INTERNAL_NETWORK_CANARY")),
  );
  await expect(new ApiClient().me()).rejects.toEqual(expect.any(ApiError));
  await expect(new ApiClient().me()).rejects.toMatchObject({
    message: "暂时连接不上服务，请稍后重试。",
  });
});
