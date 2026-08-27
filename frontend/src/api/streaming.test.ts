import { describe, expect, it, vi } from "vitest";

import { streamConfirmedConversation } from "./streaming";
import type { StreamBusinessEvent } from "./types";
import { fingerprint, planFixture, streamEvent } from "../test/fixtures";

function sseResponse(events: Array<StreamBusinessEvent | ": ping">): Response {
  const body = events.map((event) => event === ": ping" ? ": ping\n\n" : `id: ${event.event_id}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("POST planning stream", () => {
  it("sends the exact fingerprint, ignores heartbeat, and accepts one final plan", async () => {
    const started = streamEvent("run_started", { backend_mode: "direct", persistent: true }, 1);
    const completed = streamEvent("plan_completed", { travel_plan: planFixture }, 2, "finalize_plan");
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([started, ": ping", completed]));
    vi.stubGlobal("fetch", fetchMock);
    const seen: string[] = [];
    await streamConfirmedConversation("thread", { user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] }, new AbortController().signal, (event) => seen.push(event.event_type));
    expect(seen).toEqual(["run_started", "plan_completed"]);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] });
  });

  it("ignores an unknown event without crashing", async () => {
    const complete = streamEvent("plan_completed", { travel_plan: planFixture }, 1, "finalize_plan");
    const body = `event: future_event\ndata: {"safe":true}\n\nevent: plan_completed\ndata: ${JSON.stringify(complete)}\n\n`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers: { "Content-Type": "text/event-stream" } })));
    const seen: string[] = [];
    await streamConfirmedConversation("thread", { user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] }, new AbortController().signal, (event) => seen.push(event.event_type));
    expect(seen).toEqual(["plan_completed"]);
  });

  it("rejects a business event after a terminal", async () => {
    const complete = streamEvent("plan_completed", { travel_plan: planFixture }, 1, "finalize_plan");
    const extra = streamEvent("node_completed", {}, 2, "planner");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([complete, extra])));
    await expect(streamConfirmedConversation("thread", { user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] }, new AbortController().signal, () => undefined)).rejects.toMatchObject({ code: "stream_after_terminal" });
  });

  it("requires a terminal event", async () => {
    const started = streamEvent("run_started", { backend_mode: "direct", persistent: true }, 1);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([started])));
    await expect(streamConfirmedConversation("thread", { user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] }, new AbortController().signal, () => undefined)).rejects.toMatchObject({ code: "stream_disconnected" });
  });

  it("propagates AbortError as cancellation", async () => {
    const abort = new DOMException("Stopped", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
    await expect(streamConfirmedConversation("thread", { user_id: "user", draft_fingerprint: fingerprint, remember_preferences: [] }, new AbortController().signal, () => undefined)).rejects.toBe(abort);
  });
});
