import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dialog } from "./Dialog";

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

describe("Dialog", () => {
  it("provides modal semantics, locks scroll and closes on Escape", async () => {
    const onClose = vi.fn();
    render(
      <Dialog open title="Example" onClose={onClose}>
        <button>First</button>
      </Dialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "Example" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps focus and restores it when unmounted", async () => {
    const user = userEvent.setup();
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { unmount } = render(
      <Dialog open title="Focus">
        <button>First</button>
        <button>Last</button>
      </Dialog>,
    );
    await new Promise((resolve) => requestAnimationFrame(resolve));

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "First" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Last" }));
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
