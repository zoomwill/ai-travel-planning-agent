import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getConversation } from "../api/conversation";
import { streamConfirmedConversation } from "../api/streaming";
import { AppError } from "../lib/errors";
import { conversationFixture, fingerprint } from "../test/fixtures";
import { usePlanningStream } from "./usePlanningStream";

vi.mock("../api/conversation", () => ({ getConversation: vi.fn() }));
vi.mock("../api/streaming", () => ({ streamConfirmedConversation: vi.fn() }));

const mockedGetConversation = vi.mocked(getConversation);
const mockedStream = vi.mocked(streamConfirmedConversation);

describe("usePlanningStream", () => {
  it("does not start until clicked and sends the exact current fingerprint once", async () => {
    const conversation = conversationFixture();
    const dispatch = vi.fn();
    mockedStream.mockResolvedValue(undefined);
    mockedGetConversation.mockResolvedValue({ ...conversation, status: "planned", plan_available: true });
    const { result } = renderHook(() => usePlanningStream("user", "thread", dispatch));
    expect(mockedStream).not.toHaveBeenCalled();
    await act(() => result.current.startPlanning(conversation, true));
    expect(mockedStream).toHaveBeenCalledTimes(1);
    expect(mockedStream.mock.calls[0]?.[1]).toEqual({
      user_id: "user",
      draft_fingerprint: fingerprint,
      remember_preferences: ["photography", "quiet neighborhoods"],
    });
  });

  it("refreshes a stale draft and never automatically retries confirmation", async () => {
    const conversation = conversationFixture();
    const latest = conversationFixture({ draft_fingerprint: "b".repeat(64), version: 2 });
    const dispatch = vi.fn();
    mockedStream.mockRejectedValue(
      new AppError("Your trip details changed. Please review the latest version before confirming.", {
        code: "stale_draft_fingerprint",
        status: 409,
      }),
    );
    mockedGetConversation.mockResolvedValue(latest);
    const { result } = renderHook(() => usePlanningStream("user", "thread", dispatch));
    await act(() => result.current.startPlanning(conversation, false));
    expect(mockedStream).toHaveBeenCalledTimes(1);
    expect(mockedGetConversation).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith({ type: "CONVERSATION_RECEIVED", conversation: latest });
    expect(dispatch).toHaveBeenLastCalledWith(expect.objectContaining({ type: "SHOW_ERROR" }));
  });

  it("aborts on Stop, resyncs, and never dispatches a final plan", async () => {
    const conversation = conversationFixture();
    const dispatch = vi.fn();
    mockedGetConversation.mockResolvedValue(conversation);
    mockedStream.mockImplementation(
      async (_threadId, _request, signal) =>
        new Promise<void>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("Stopped", "AbortError")),
            { once: true },
          );
        }),
    );
    const { result } = renderHook(() => usePlanningStream("user", "thread", dispatch));
    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.startPlanning(conversation, false);
    });
    await act(() => result.current.stopPlanning());
    await act(async () => pending);
    expect(mockedGetConversation).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith({ type: "STOPPED" });
    expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: "PLAN_RESTORED" }));
  });
});
