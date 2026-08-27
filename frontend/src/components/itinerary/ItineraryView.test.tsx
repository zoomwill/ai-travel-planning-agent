import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { planFixture } from "../../test/fixtures";
import { ItineraryView } from "./ItineraryView";

describe("ItineraryView", () => {
  it("renders summary, flight, hotel, days, review, and demo disclosure", () => {
    render(<ItineraryView plan={planFixture} review={{ reviewRound: 1, decision: "accept", scores: { completeness: 90, feasibility: 88, personalization: 92, budget_fit: 95, overall_score: 91 }, critique: "The plan is ready." }} />);
    expect(screen.getByRole("heading", { name: /Cleveland.*Tokyo/ })).toBeInTheDocument();
    expect(screen.getByText(/Mock Pacific/)).toBeInTheDocument();
    expect(screen.getByText("Tokyo Quiet Hotel")).toBeInTheDocument();
    expect(screen.getByText("Arrival and evening walk")).toBeInTheDocument();
    expect(screen.getByText("Final review summary")).toBeInTheDocument();
    expect(screen.getByText(/not live booking inventory/)).toBeInTheDocument();
  });

  it("shows a budget warning supplied by the backend", () => {
    render(<ItineraryView plan={{ ...planFixture, budget_warning: "Estimated cost exceeds your budget." }} />);
    expect(screen.getByText("Estimated cost exceeds your budget.")).toBeInTheDocument();
  });
});
