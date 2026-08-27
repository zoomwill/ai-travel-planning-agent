import { describe, expect, it, vi } from "vitest";

import { createThread, getOrCreateIdentity, getRecentThreads, rememberThread } from "./storage";

describe("local demo storage", () => {
  it("regenerates invalid IDs and stores only identity pointers", () => {
    localStorage.setItem("travel-planner:user-id", "not-valid");
    localStorage.setItem("travel-planner:thread-id", "not-valid");
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("11111111-1111-4111-8111-111111111111")
      .mockReturnValueOnce("22222222-2222-4222-8222-222222222222");
    const identity = getOrCreateIdentity();
    expect(identity).toEqual({
      userId: "11111111-1111-4111-8111-111111111111",
      threadId: "22222222-2222-4222-8222-222222222222",
    });
    const allStorage = JSON.stringify({ ...localStorage });
    expect(allStorage).not.toContain("messages");
    expect(allStorage).not.toContain("travel_plan");
    expect(allStorage).not.toContain("preferences");
  });

  it("keeps at most ten recent thread metadata records", () => {
    for (let index = 0; index < 12; index += 1) {
      rememberThread(`00000000-0000-4000-8000-${String(index).padStart(12, "0")}`, `Trip ${index}`);
    }
    expect(getRecentThreads()).toHaveLength(10);
    expect(getRecentThreads()[0]?.title).toBe("Trip 11");
  });

  it("creates a new thread without changing the local user ID", () => {
    const identity = getOrCreateIdentity();
    const next = createThread();
    expect(next).not.toBe(identity.threadId);
    expect(localStorage.getItem("travel-planner:user-id")).toBe(identity.userId);
  });
});
