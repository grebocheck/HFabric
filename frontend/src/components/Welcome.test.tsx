import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Welcome } from "./Welcome";

afterEach(cleanup);

describe("Welcome", () => {
  it("names the core surfaces and hides the STUB note in real mode", () => {
    render(<Welcome stubMode={false} onClose={() => {}} />);
    expect(screen.getByText("Welcome to HFabric")).toBeTruthy();
    expect(screen.getByText("Images")).toBeTruthy();
    expect(screen.getByText("LLM")).toBeTruthy();
    expect(screen.getByText("System")).toBeTruthy();
    expect(screen.queryByText(/STUB mode/i)).toBeNull();
  });

  it("surfaces the STUB-mode note when in stub mode", () => {
    render(<Welcome stubMode={true} onClose={() => {}} />);
    expect(screen.getByText(/STUB mode/i)).toBeTruthy();
  });

  it("calls onClose when Get started is clicked", async () => {
    const onClose = vi.fn();
    render(<Welcome stubMode={false} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Get started" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
