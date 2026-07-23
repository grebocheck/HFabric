import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

afterEach(cleanup);

function Broken({ fail }: { fail: boolean }) {
  if (fail) throw new Error("render exploded");
  return <div>healthy</div>;
}

describe("ErrorBoundary", () => {
  it("shows recovery actions and can retry rendering", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    let fail = true;
    const { rerender } = render(
      <ErrorBoundary><Broken fail={fail} /></ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("render exploded")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download diagnostics" })).toBeTruthy();

    fail = false;
    rerender(<ErrorBoundary><Broken fail={fail} /></ErrorBoundary>);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("healthy")).toBeTruthy();
    consoleSpy.mockRestore();
  });
});
