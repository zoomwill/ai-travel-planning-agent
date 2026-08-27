import { describe, expect, it } from "vitest";

import { appReducer, initialAppState } from "./appReducer";
import { planFixture, streamEvent } from "../test/fixtures";

describe("planning progress reducer", () => {
  it("tracks five searches without depending on completion order", () => {
    let state = appReducer(initialAppState, { type: "PLAN_START" });
    const kinds = ["weather", "flights", "route", "attractions", "hotels"] as const;
    let sequence = 1;
    for (const kind of kinds) {
      state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("search_started", { search_kind: kind }, sequence++) });
    }
    for (const kind of ["route", "weather", "hotels", "flights", "attractions"] as const) {
      state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("search_completed", { search_kind: kind, status: "ok", result_count: 1 }, sequence++) });
    }
    expect(Object.values(state.progress.searches)).toEqual(Array(5).fill("completed"));
    expect(state.progress.stages.search).toBe("completed");
  });

  it("shows review, revision, and final structured plan", () => {
    let state = appReducer(initialAppState, { type: "PLAN_START" });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("review_completed", { review_round: 1, decision: "revise", scores: { completeness: 80, feasibility: 75, personalization: 90, budget_fit: 70, overall_score: 79 }, issue_codes: ["budget_overrun"], critique: "Choose a lower-cost hotel.", suggested_changes: ["Use an existing lower-cost option."] }) });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("revision_started", { review_round: 1, issue_codes: ["budget_overrun"], suggested_changes: ["Use an existing lower-cost option."] }) });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("plan_completed", { travel_plan: planFixture }) });
    expect(state.progress.reviews[0]?.decision).toBe("revise");
    expect(state.progress.revisionRound).toBe(1);
    expect(state.phase).toBe("planned");
    expect(state.finalPlan?.requirements.destination).toBe("Tokyo");
  });

  it("never creates a final plan from an error terminal", () => {
    const state = appReducer(initialAppState, { type: "STREAM_EVENT", event: streamEvent("error", { error_code: "stream_graph_failed", safe_message: "Planning failed.", recoverable: true }) });
    expect(state.phase).toBe("error");
    expect(state.finalPlan).toBeNull();
  });
});
