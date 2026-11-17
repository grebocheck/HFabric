import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

const mocks = vi.hoisted(() => ({ runtimeSettings: vi.fn(), settingsOverrides: vi.fn(), saveSettingsOverrides: vi.fn() }));
vi.mock("../api/client", () => ({ api: mocks }));
vi.mock("./LlamaRuntime", () => ({ LlamaRuntime: () => null }));
afterEach(cleanup);

it("saves only edited defaults and preserves edits made while saving", async () => {
  const values = { default_steps: 28, flux2_quant: "bnb-nf4" };
  const writable = { values, groups: [{ id: "image_defaults", label: "Image defaults" }], path: "settings.json", schema: [
    { key: "default_steps", label: "Steps", group: "image_defaults", kind: "integer", min: 1, max: 150 },
    { key: "flux2_quant", label: "FLUX.2 quant", group: "image_defaults", kind: "choice", choices: [] },
  ] };
  mocks.runtimeSettings.mockResolvedValue(null);
  mocks.settingsOverrides.mockResolvedValue(writable);
  let finish!: (value: unknown) => void;
  mocks.saveSettingsOverrides.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const user = userEvent.setup();
  render(<SettingsPanel />);
  const input = await screen.findByRole("spinbutton", { name: /Steps/ });
  expect(screen.queryByText("FLUX.2 quant")).toBeNull();
  fireEvent.change(input, { target: { value: "36" } });
  await user.click(screen.getByRole("button", { name: "Save", exact: true }));
  fireEvent.change(input, { target: { value: "48" } });
  await act(async () => finish({ ...writable, values: { ...values, default_steps: 36 } }));
  await waitFor(() => expect((input as HTMLInputElement).value).toBe("48"));
  expect(mocks.saveSettingsOverrides).toHaveBeenCalledWith({ default_steps: 36 });
  expect(screen.getByText("1 unsaved")).toBeTruthy();
});

it("restores unapplied defaults after remount and clears them on Revert", async () => {
  const writable = { values: { default_steps: 28 }, groups: [{ id: "image_defaults", label: "Image defaults" }], path: "settings.json", schema: [
    { key: "default_steps", label: "Steps", group: "image_defaults", kind: "integer", min: 1, max: 150 },
  ] };
  mocks.runtimeSettings.mockResolvedValue(null);
  mocks.settingsOverrides.mockResolvedValue(writable);
  const first = render(<SettingsPanel />);
  fireEvent.change(await screen.findByRole("spinbutton", { name: /Steps/ }), { target: { value: "52" } });
  first.unmount();
  const second = render(<SettingsPanel />);
  expect((await screen.findByRole("spinbutton", { name: /Steps/ }) as HTMLInputElement).value).toBe("52");
  await userEvent.setup().click(screen.getByRole("button", { name: "Revert", exact: true }));
  second.unmount();
  render(<SettingsPanel />);
  expect((await screen.findByRole("spinbutton", { name: /Steps/ }) as HTMLInputElement).value).toBe("28");
});
