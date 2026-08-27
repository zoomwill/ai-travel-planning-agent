import { describe, expect, it, vi } from "vitest";

import { getConversation, sendConversationMessage } from "./conversation";
import { requestJson } from "./client";
import { AppError } from "../lib/errors";
import { conversationFixture } from "../test/fixtures";
import { z } from "zod";

function response(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("JSON API client", () => {
  it("GETs and validates a conversation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(conversationFixture()));
    vi.stubGlobal("fetch", fetchMock);
    const result = await getConversation("thread one", "user one");
    expect(result.draft.destination).toBe("Tokyo");
    expect(fetchMock.mock.calls[0]?.[0]).toContain("thread%20one/conversation?user_id=user%20one");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("POSTs a message exactly once", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(conversationFixture()));
    vi.stubGlobal("fetch", fetchMock);
    await sendConversationMessage("thread", { user_id: "user", message: "Tokyo", start_new_trip: false });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: "user", message: "Tokyo", start_new_trip: false });
  });

  it.each([
    [409, "stale_draft_fingerprint", "changed"],
    [422, "validation_error", "not accepted"],
    [503, "conversational_intake_requires_llm", "AI conversation service"],
  ])("maps HTTP %i to safe text", async (status, code, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ detail: { code, message: "private" } }, status)));
    await expect(requestJson("/test", z.object({ ok: z.boolean() }), { method: "POST" })).rejects.toMatchObject({ status, code, message: expect.stringContaining(message) });
  });

  it("preserves X-Request-ID on a safe error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ detail: { code: "bad" } }, 500, { "X-Request-ID": "req-safe" })));
    await expect(requestJson("/test", z.object({}), { method: "POST" })).rejects.toMatchObject({ requestId: "req-safe" });
  });

  it("handles a non-JSON error body without exposing it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("FAKE_PRIVATE_BACKEND_EXCEPTION", 500, { "Content-Type": "text/plain" })));
    const error = await requestJson("/test", z.object({}), { method: "POST" }).catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(AppError);
    expect(String(error)).not.toContain("FAKE_PRIVATE_BACKEND_EXCEPTION");
  });

  it("reports invalid successful JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("not-json")));
    await expect(requestJson("/test", z.object({ ok: z.boolean() }))).rejects.toMatchObject({ code: "response_invalid_json" });
  });

  it("reports network failure after one safe GET retry", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("private network detail"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(requestJson("/test", z.object({ ok: z.boolean() }))).rejects.toMatchObject({ code: "network_error" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry an aborted GET", async () => {
    const controller = new AbortController();
    controller.abort();
    const abort = new DOMException("Aborted", "AbortError");
    const fetchMock = vi.fn().mockRejectedValue(abort);
    vi.stubGlobal("fetch", fetchMock);
    await expect(requestJson("/test", z.object({}), { signal: controller.signal })).rejects.toBe(abort);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
