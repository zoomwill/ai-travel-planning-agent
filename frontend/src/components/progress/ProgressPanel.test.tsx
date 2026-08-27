import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { freshProgress } from "../../state/appReducer";
import { ProgressPanel } from "./ProgressPanel";

it("renders user-friendly stages, five searches, and Stop", () => {
  const progress = freshProgress();
  progress.searches.weather = "completed";
  progress.searches.flights = "running";
  render(<ProgressPanel progress={progress} onStop={vi.fn()} />);
  expect(screen.getByText("Understanding preferences")).toBeInTheDocument();
  expect(screen.getByText("Flights")).toBeInTheDocument();
  expect(screen.getByText("Hotels")).toBeInTheDocument();
  expect(screen.getByText("Attractions")).toBeInTheDocument();
  expect(screen.getByText("Weather")).toBeInTheDocument();
  expect(screen.getByText("Route")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
});
