import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  getConversation,
  getThreadState,
  resetConversation,
  sendConversationMessage,
} from "../api/conversation";
import { AppError } from "../lib/errors";
import { conversationFixture, planFixture } from "../test/fixtures";
import { useConversation } from "./useConversation";

vi.mock("../api/conversation", () => ({
  getConversation: vi.fn(),
  getThreadState: vi.fn(),
  resetConversation: vi.fn(),
  sendConversationMessage: vi.fn(),
}));

const mockedGet = vi.mocked(getConversation);
const mockedGetState = vi.mocked(getThreadState);
const mockedReset = vi.mocked(resetConversation);
const mockedSend = vi.mocked(sendConversationMessage);

describe("useConversation", () => {
  it("does not restore a plan from an errored checkpoint", async () => {
    mockedGet.mockResolvedValue(conversationFixture({ status: "planned", plan_available: true }));
    mockedGetState.mockResolvedValue({ thread_id: "thread", status: "error", travel_plan: planFixture, review_round: 3, final_score: null });
    const updateTitle = vi.fn();
    const { result } = renderHook(() => useConversation("user", "thread", updateTitle));
    await waitFor(() => expect(mockedGetState).toHaveBeenCalled());
    expect(result.current.state.finalPlan).toBeNull();
  });

  it("ignores an old account request even if an aborted promise resolves later", async () => {
    let finishOld!: (value: ReturnType<typeof conversationFixture>) => void;
    mockedGet.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    mockedGet.mockResolvedValue(conversationFixture({ draft: { ...conversationFixture().draft, destination: "Paris" } }));
    const updateTitle = vi.fn();
    const { result, rerender } = renderHook(({ user }) => useConversation(user, "same-thread", updateTitle), { initialProps: { user: "a" } });
    rerender({ user: "b" });
    await waitFor(() => expect(result.current.state.conversation?.draft.destination).toBe("Paris"));
    await act(async () => { finishOld(conversationFixture()); await Promise.resolve(); });
    expect(result.current.state.conversation?.draft.destination).toBe("Paris");
    expect(updateTitle).not.toHaveBeenCalledWith("Tokyo");
  });
  it("turns a missing persisted conversation into a new empty UI", async () => {
    mockedGet.mockRejectedValue(
      new AppError("No conversation.", { code: "intake_not_found", status: 404 }),
    );
    const updateTitle = vi.fn();
    const { result } = renderHook(() => useConversation("user", "thread", updateTitle));
    await waitFor(() => expect(result.current.state.phase).toBe("collecting"));
    expect(result.current.state.conversation).toBeNull();
  });

  it("restores an existing final plan through state read without planning", async () => {
    const planned = conversationFixture({ status: "planned", can_confirm: false, plan_available: true });
    mockedGet.mockResolvedValue(planned);
    mockedGetState.mockResolvedValue({
      thread_id: planned.thread_id,
      status: "complete",
      travel_plan: planFixture,
      review_round: 1,
      final_score: 91,
    });
    const updateTitle = vi.fn();
    const { result } = renderHook(() => useConversation("user", "thread", updateTitle));
    await waitFor(() => expect(result.current.state.finalPlan).toEqual(planFixture));
    expect(result.current.state.phase).toBe("planned");
    expect(mockedSend).not.toHaveBeenCalled();
  });

  it("resets only the current backend conversation", async () => {
    const ready = conversationFixture();
    const empty = conversationFixture({
      status: "collecting",
      can_confirm: false,
      draft: {
        origin: null,
        destination: null,
        start_date: null,
        end_date: null,
        duration_days: null,
        budget: null,
        currency: null,
        travelers: null,
        guest_nationality: null,
        preferences: [],
      },
      missing_fields: ["origin", "destination", "start_date", "end_date", "budget", "travelers"],
      messages: [],
    });
    mockedGet.mockResolvedValue(ready);
    mockedReset.mockResolvedValue(empty);
    const updateTitle = vi.fn();
    const { result } = renderHook(() => useConversation("user", "thread", updateTitle));
    await waitFor(() => expect(result.current.state.conversation).toEqual(ready));
    await act(() => result.current.reset());
    expect(mockedReset).toHaveBeenCalledWith("thread", "user", expect.any(AbortSignal), undefined);
    expect(result.current.state.conversation?.draft.destination).toBeNull();
    expect(updateTitle).toHaveBeenLastCalledWith("New trip");
  });
});
