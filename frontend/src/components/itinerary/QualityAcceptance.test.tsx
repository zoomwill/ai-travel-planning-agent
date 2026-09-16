import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { planQualitySchema, travelPlanSchema } from "../../api/schemas";
import { planFixture, streamEvent } from "../../test/fixtures";
import { appReducer, initialAppState } from "../../state/appReducer";
import { ProgressPanel } from "../progress/ProgressPanel";
import { ItineraryView } from "./ItineraryView";

const forced = { ...planFixture, quality: planQualitySchema.parse({ review_status: "forced_finalized", review_rounds: 3, final_score: 62.5, finalization_reason: "max_review_rounds_reached", issue_codes: ["noncritical_data_unavailable"] }), warnings: ["route_unavailable" as const] };

describe("P19 terminal quality", () => {
  it("ends forced finalization, keeps real score and issues, and ignores late progress", () => {
    let state = appReducer(initialAppState, { type: "PLAN_START" });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("revision_started", { review_round: 3, issue_codes: ["noncritical_data_unavailable"], suggested_changes: ["Check unavailable data."] }) });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("plan_completed", { travel_plan: forced }) });
    const terminal = state;
    for (const event of [streamEvent("search_started", { search_kind: "route" }), streamEvent("node_started", {}, 30, "planner"), streamEvent("revision_started", { review_round: 4, issue_codes: [], suggested_changes: [] })]) {
      state = appReducer(state, { type: "STREAM_EVENT", event });
    }
    expect(state).toBe(terminal);
    render(<><ItineraryView plan={forced} /><ProgressPanel progress={state.progress} /></>);
    expect(screen.getAllByText("Draft generated — review needed").length).toBeGreaterThan(0);
    expect(screen.getByText("62.5")).toBeInTheDocument();
    expect(screen.getByText(/Maximum review rounds reached/)).toBeInTheDocument();
    expect(screen.getByText(/No verified intercity/)).toBeInTheDocument();
    expect(screen.queryByText(/Improving your itinerary/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("In progress")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.getByText(/Check-in.*Check-out.*5 nights/)).toBeInTheDocument();
  });

  it("restores the same quality without ephemeral SSE reviews", () => {
    const state = appReducer(initialAppState, { type: "PLAN_RESTORED", plan: forced });
    expect(state.progress.reviews).toEqual([]);
    expect(state.progress.terminal).toBe(true);
    render(<ItineraryView plan={state.finalPlan!} />);
    expect(screen.getByText("62.5")).toBeInTheDocument();
    expect(screen.getByText(/Some non-critical travel data/)).toBeInTheDocument();
  });

  it("accepted is not a factual verification guarantee", () => {
    render(<ItineraryView plan={{ ...forced, quality: { ...forced.quality, review_status: "accepted", finalization_reason: "threshold_reached", final_score: 95, review_rounds: 1 } }} />);
    expect(screen.getAllByText(/Reviewer accepted — verify travel details/).length).toBeGreaterThan(0);
    expect(screen.getByText(/not live booking inventory/)).toBeInTheDocument();
    expect(screen.getByText(/No verified intercity/)).toBeInTheDocument();
  });

  it("old payload defaults unknown, not accepted; rejects unrecognized new fields", () => {
    const old = { ...planFixture } as Partial<typeof planFixture>;
    delete old.quality;
    delete old.warnings;
    const restored = travelPlanSchema.parse(old);
    expect(restored.quality).toBeNull();
    render(<ItineraryView plan={restored} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText(/Historical route information is unverified/)).toBeInTheDocument();
    expect(travelPlanSchema.safeParse({ ...old, quality: { ...forced.quality, token: "synthetic" } }).success).toBe(false);
    expect(travelPlanSchema.safeParse({ ...old, warnings: ["arbitrary private text"] }).success).toBe(false);
  });

  it("a critical error stops progress and cannot be followed by a plan", () => {
    let state = appReducer(initialAppState, { type: "PLAN_START" });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("search_started", { search_kind: "flights" }) });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("error", { error_code: "critical_search_failed", safe_message: "Flights unavailable.", recoverable: true }) });
    state = appReducer(state, { type: "STREAM_EVENT", event: streamEvent("plan_completed", { travel_plan: forced }) });
    expect(state.finalPlan).toBeNull();
    expect(state.progress.searches.flights).toBe("stopped");
    expect(state.phase).toBe("error");
  });
});
