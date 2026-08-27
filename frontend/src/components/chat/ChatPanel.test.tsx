import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { conversationFixture } from "../../test/fixtures";
import { ChatPanel } from "./ChatPanel";

describe("ChatPanel", () => {
  it("shows welcome prompts and fills without auto-sending", async () => {
    const send = vi.fn();
    render(<ChatPanel conversation={null} phase="collecting" optimisticMessage={null} failedMessage={null} onSend={send} />);
    expect(screen.getByRole("heading", { name: "Where do you want to go?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Plan a 5-day photography trip to Tokyo." }));
    expect(screen.getByLabelText("Describe your trip")).toHaveValue("Plan a 5-day photography trip to Tokyo.");
    expect(send).not.toHaveBeenCalled();
  });

  it("submits Enter and preserves Shift+Enter", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    render(<ChatPanel conversation={null} phase="collecting" optimisticMessage={null} failedMessage={null} onSend={send} />);
    const input = screen.getByLabelText("Describe your trip");
    await userEvent.type(input, "Tokyo{shift>}{enter}{/shift}photos");
    expect(input).toHaveValue("Tokyo\nphotos");
    await userEvent.keyboard("{Enter}");
    expect(send).toHaveBeenCalledWith("Tokyo\nphotos");
  });

  it("renders user and assistant bubbles in a polite live region", () => {
    const { container } = render(<ChatPanel conversation={conversationFixture()} phase="collecting" optimisticMessage={null} failedMessage={null} onSend={vi.fn()} />);
    expect(screen.getByText("I want to visit Tokyo.")).toBeInTheDocument();
    expect(screen.getByText("What dates and budget work for you?")).toBeInTheDocument();
    expect(container.querySelector('[aria-live="polite"]')).toBeInTheDocument();
  });

  it("disables sending while a message is in flight and offers retry", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<ChatPanel conversation={null} phase="collecting" optimisticMessage="Tokyo" failedMessage={null} onSend={send} />);
    expect(screen.getByLabelText("Send message")).toBeDisabled();
    rerender(<ChatPanel conversation={null} phase="error" optimisticMessage={null} failedMessage="Tokyo" onSend={send} />);
    await userEvent.click(screen.getByRole("button", { name: /Retry last message/ }));
    expect(send).toHaveBeenCalledWith("Tokyo");
  });

  it("enforces the backend 4000 character maximum", () => {
    render(<ChatPanel conversation={null} phase="collecting" optimisticMessage={null} failedMessage={null} onSend={vi.fn()} />);
    const input = screen.getByLabelText("Describe your trip");
    fireEvent.change(input, { target: { value: "x".repeat(4000) } });
    expect(screen.getByText("4000/4000")).toBeInTheDocument();
    expect(input).toHaveAttribute("maxlength", "4000");
  });
});
