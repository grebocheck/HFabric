import axe from "axe-core";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CommandPalette } from "./CommandPalette";
import { Select } from "./Select";
import { Welcome } from "./Welcome";

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

async function expectNoSeriousViolations() {
  const results = await axe.run(document.body, {
    // jsdom has no layout/paint information, so contrast is covered by browser
    // QA while structural rules run here.
    rules: { "color-contrast": { enabled: false } },
  });
  const violations = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(violations.map(({ id, help }) => ({ id, help }))).toEqual([]);
}

describe("critical surface accessibility", () => {
  it("keeps the first-run dialog structurally accessible", async () => {
    render(<Welcome stubMode={false} onClose={() => undefined} />);
    await expectNoSeriousViolations();
  });

  it("keeps palette and custom select ARIA contracts valid", async () => {
    render(
      <>
        <CommandPalette
          open
          commands={[{ id: "images", label: "Go to Images", run: () => undefined }]}
          onClose={() => undefined}
        />
        <Select
          ariaLabel="Model"
          value=""
          options={[{ value: "model", label: "Model" }]}
          onChange={() => undefined}
        />
      </>,
    );
    await expectNoSeriousViolations();
  });
});
