import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { conversationFixture } from "../../test/fixtures";
import { TripDraftPanel } from "./TripDraftPanel";

describe("TripDraftPanel", () => {
  it("shows unknown fields as Not set and missing checklist items", () => {
    const conversation = conversationFixture({
      status: "collecting",
      can_confirm: false,
      draft: {
        origin: null, destination: "Tokyo", start_date: null, end_date: null,
        duration_days: null, budget: null, currency: null, travelers: null, preferences: [],
      },
      missing_fields: ["origin", "start_date", "end_date", "budget", "currency", "travelers"],
    });
    render(<TripDraftPanel conversation={conversation} planning={false} onConfirm={vi.fn()} />);
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(1);
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it("renders dates, currency, preferences, and explicit confirmation", async () => {
    const confirm = vi.fn();
    render(<TripDraftPanel conversation={conversationFixture()} planning={false} onConfirm={confirm} />);
    expect(screen.getByText(/Oct 12, 2027/)).toBeInTheDocument();
    expect(screen.getByText(/3,000/)).toBeInTheDocument();
    expect(screen.getByText("photography")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Confirm & Build My Trip/ }));
    expect(confirm).toHaveBeenCalledWith(false);
  });

  it("remembers only current explicit preferences when selected by its parent", async () => {
    const confirm = vi.fn();
    render(<TripDraftPanel conversation={conversationFixture()} planning={false} onConfirm={confirm} />);
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /Confirm & Build My Trip/ }));
    expect(confirm).toHaveBeenCalledWith(true);
  });
});
