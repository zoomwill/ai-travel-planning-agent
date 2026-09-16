import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { planFixture } from "../../test/fixtures";
import { ItineraryView } from "./ItineraryView";

describe("ItineraryView", () => {
  it("renders summary, flight, hotel, days, review, and demo disclosure", () => {
    render(<ItineraryView plan={planFixture} />);
    expect(screen.getByRole("heading", { name: /Cleveland.*Tokyo/ })).toBeInTheDocument();
    expect(screen.getByText(/Mock Pacific/)).toBeInTheDocument();
    expect(screen.getByText("Tokyo Quiet Hotel")).toBeInTheDocument();
    expect(screen.getByText("Arrival and evening walk")).toBeInTheDocument();
    expect(screen.getByText("Final review summary")).toBeInTheDocument();
    expect(screen.getAllByText("Demo").length).toBeGreaterThan(0);
    expect(screen.getByText(/deterministic sample data/)).toBeInTheDocument();
    expect(screen.getByText(/Outbound one-way fare.*Return flight is not included/)).toBeInTheDocument();
  });

  it("shows a budget warning supplied by the backend", () => {
    render(<ItineraryView plan={{ ...planFixture, budget_warning: "Estimated cost exceeds your budget." }} />);
    expect(screen.getByText("Estimated cost exceeds your budget.")).toBeInTheDocument();
  });

  it("renders mixed sources, connecting segments, nullable rating, and no booking action", () => {
    const mixedPlan = {
      ...planFixture,
      flight: {
        ...planFixture.flight,
        airline: "United Airlines",
        flight_number: "UA123",
        stops: 1,
        data_source: "duffel_test" as const,
        segments: [
          { flight_number: "UA123", airline: "United Airlines", origin_iata_code: "CLE", destination_iata_code: "ORD", departure_time: "2027-10-12T08:30:00Z", arrival_time: "2027-10-12T10:00:00Z", duration_minutes: 90 },
          { flight_number: "UA456", airline: "United Airlines", origin_iata_code: "ORD", destination_iata_code: "NRT", departure_time: "2027-10-12T12:00:00Z", arrival_time: "2027-10-13T01:00:00Z", duration_minutes: 780 },
        ],
      },
      hotel: {
        ...planFixture.hotel,
        rating: null,
        distance_to_center_km: null,
        data_source: "demo_fallback" as const,
      },
      data_sources: {
        flights: "duffel_test" as const,
        hotels: "demo_fallback" as const,
        attractions: "demo" as const,
        weather: "demo" as const,
        route: "demo" as const,
      },
    };

    render(<ItineraryView plan={mixedPlan} />);
    expect(screen.getAllByText("Duffel Test · Test data").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Demo Fallback").length).toBeGreaterThan(0);
    expect(screen.getByText("United Airlines · UA456")).toBeInTheDocument();
    expect(screen.getByText(/Cleveland.*Tokyo.*1 stop/)).toBeInTheDocument();
    expect(screen.getByText(/Rating unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /book|reserve|pay|checkout/i })).not.toBeInTheDocument();
  });

  it("labels live-mode source without calling it real-time", () => {
    render(<ItineraryView plan={{ ...planFixture, flight: { ...planFixture.flight, data_source: "duffel_live" }, data_sources: { ...planFixture.data_sources, flights: "duffel_live" } }} />);
    expect(screen.getAllByText("Duffel Live").length).toBeGreaterThan(0);
    expect(screen.queryByText(/real-time/i)).not.toBeInTheDocument();
  });

  it("labels LiteAPI Sandbox and excluded fees without inventing stars or booking", () => {
    render(<ItineraryView plan={{ ...planFixture,
      flight: { ...planFixture.flight, data_source: "duffel_test" },
      hotel: { ...planFixture.hotel, data_source: "liteapi_sandbox", rating: null,
        total_stay_price: "501.01", stay_nights: 5, room_name: "Standard Room",
        board_name: "Room Only", has_excluded_fees: true },
      data_sources: { ...planFixture.data_sources, flights: "duffel_test", hotels: "liteapi_sandbox" },
    }} />);
    expect(screen.getAllByText("LiteAPI Sandbox").length).toBeGreaterThan(0);
    expect(screen.getByText(/Additional property fees/)).toBeInTheDocument();
    expect(screen.getByText(/Total stay quote/)).toHaveTextContent("501.01");
    expect(screen.getByText(/Rating unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/not production inventory/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /book|reserve|pay|checkout/i })).not.toBeInTheDocument();
  });
});
