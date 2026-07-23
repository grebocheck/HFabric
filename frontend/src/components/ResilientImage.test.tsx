import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResilientImage } from "./ResilientImage";

afterEach(cleanup);

describe("ResilientImage", () => {
  it("falls back from a thumbnail to the original and then to a placeholder", () => {
    render(
      <ResilientImage
        sources={["/missing-thumb.png", "/original.png"]}
        alt="Generated result"
      />,
    );
    const image = screen.getByRole("img", { name: "Generated result" });
    expect(image.getAttribute("src")).toBe("/missing-thumb.png");
    fireEvent.error(image);
    expect(screen.getByRole("img", { name: "Generated result" }).getAttribute("src")).toBe("/original.png");
    fireEvent.error(screen.getByRole("img", { name: "Generated result" }));
    expect(screen.getByRole("img", { name: "Generated result" }).textContent).toContain("Image unavailable");
  });
});
