import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { requestEventStream, requestJson } from "../api/client";
import { clearSessionPointers, getOrCreateIdentity, getRecentThreads, rememberThread } from "../lib/storage";

describe("authenticated network boundary", () => {
  it("gets an access token before JSON and POST SSE", async () => {
    const token = vi.fn().mockResolvedValue("synthetic-unit-access-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response('{"ok":true}'))
      .mockResolvedValueOnce(new Response(": ping\n\n", { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetchMock);
    await requestJson("/api/v1/test", z.object({ ok: z.boolean() }), { getAccessToken: token });
    await requestEventStream("/api/v1/stream", {}, new AbortController().signal, token);
    expect(token).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) {
      expect(call[1].headers.Authorization).toBe("Bearer synthetic-unit-access-token");
    }
    expect(localStorage.getItem("access_token")).toBeNull();
  });
  it.each([401, 403, 429])("never replays a rejected POST (%i)", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"detail":{"code":"safe"}}', { status }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(requestJson("/api/v1/test", z.object({}), { method: "POST",
      getAccessToken: () => Promise.resolve("synthetic") })).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("does not send a cancelled mutation after token acquisition", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(requestEventStream("/api/v1/stream", {}, controller.signal, () => {
      controller.abort(); return Promise.resolve("synthetic");
    })).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("isolates local metadata and clears only the signed-out user's pointers", () => {
    localStorage.clear();
    const a = getOrCreateIdentity("account-a");
    const b = getOrCreateIdentity("account-b");
    rememberThread(a.threadId, "Tokyo", "account-a");
    rememberThread(b.threadId, "Paris", "account-b");
    expect(localStorage.getItem("travel-planner:user-id")).toBeNull();
    expect(getRecentThreads("account-b")[0]?.title).toBe("Paris");
    clearSessionPointers("account-a");
    expect(getRecentThreads("account-a")).toEqual([]);
    expect(getRecentThreads("account-b")[0]?.title).toBe("Paris");
  });
});
