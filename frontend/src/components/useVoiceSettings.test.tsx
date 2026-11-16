import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceEngineSettings, VoiceEngineStatus } from "../types";
import { useVoiceSettings } from "./useVoiceSettings";
import {
  nativeRoutingSettingsPatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
} from "./voiceHelpers";

const mocks = vi.hoisted(() => ({ status: vi.fn(), settings: vi.fn() }));
vi.mock("../api/client", () => ({
  api: { voiceEngineStatus: mocks.status, voiceEngineSettings: mocks.settings },
}));

function snapshot(settings: Partial<VoiceEngineSettings> = {}): VoiceEngineStatus {
  const defaults = nativeSettingsToVoiceState({});
  return {
    settings: {
      ...nativeRoutingSettingsPatch(defaults),
      ...nativeTuningSettingsPatch(defaults),
      ...settings,
    },
  } as VoiceEngineStatus;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

async function setup() {
  mocks.status.mockResolvedValue(snapshot());
  const hook = renderHook(useVoiceSettings);
  await act(async () => {
    await hook.result.current.refresh();
  });
  return hook;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Voice settings ownership", () => {
  it("keeps unsaved tuning when bypass or a status poll changes another field", async () => {
    const { result } = await setup();
    act(() => result.current.updateDraft({ pitch: 8 }));
    mocks.settings.mockResolvedValue(snapshot({ pass_through: true }));
    await act(async () => {
      await result.current.applySettings("bypass", { pass_through: true });
    });
    expect(result.current.draft.pitch).toBe(8);
    expect(result.current.draft.passThrough).toBe(true);
    expect(result.current.tuningDirty).toBe(true);
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.draft.pitch).toBe(8);
  });

  it.each([12, 0])("preserves an edit to %s made while Apply is waiting", async (pitch) => {
    const { result } = await setup();
    const save = deferred<VoiceEngineStatus>();
    mocks.settings.mockReturnValue(save.promise);
    act(() => result.current.updateDraft({ pitch: 5 }));
    let applied!: Promise<boolean>;
    await act(async () => {
      applied = result.current.applySettings("apply", { pitch: 5 });
    });
    act(() => result.current.updateDraft({ pitch }));
    await act(async () => {
      save.resolve(snapshot({ pitch: 5 }));
      await applied;
    });
    expect(result.current.draft.pitch).toBe(pitch);
    expect(result.current.tuningDirty).toBe(true);
  });

  it("uses canonical server values after a successful Apply", async () => {
    const { result } = await setup();
    act(() => result.current.updateDraft({ pitch: 30 }));
    mocks.settings.mockResolvedValue(snapshot({ pitch: 24 }));
    await act(async () => {
      await result.current.applySettings("apply", { pitch: 30 });
    });
    expect(result.current.draft.pitch).toBe(24);
    expect(result.current.tuningDirty).toBe(false);
  });

  it("ignores a poll started before a successful write", async () => {
    const { result } = await setup();
    const poll = deferred<VoiceEngineStatus>();
    mocks.status.mockReturnValue(poll.promise);
    let refreshed!: Promise<VoiceEngineStatus | null>;
    act(() => {
      refreshed = result.current.refresh();
      result.current.updateDraft({ pitch: 7 });
    });
    mocks.settings.mockResolvedValue(snapshot({ pitch: 7 }));
    await act(async () => {
      await result.current.applySettings("apply", { pitch: 7 });
    });
    await act(async () => {
      poll.resolve(snapshot({ pitch: 0 }));
      await refreshed;
    });
    expect(result.current.draft.pitch).toBe(7);
    expect(result.current.status?.settings.pitch).toBe(7);
    expect(result.current.tuningDirty).toBe(false);
  });

  it("keeps only the latest of overlapping polls", async () => {
    const { result } = await setup();
    const first = deferred<VoiceEngineStatus>();
    mocks.status.mockReturnValueOnce(first.promise).mockResolvedValueOnce(snapshot({ pitch: 9 }));
    let earlier!: Promise<VoiceEngineStatus | null>;
    act(() => {
      earlier = result.current.refresh();
    });
    await act(async () => {
      await result.current.refresh();
    });
    await act(async () => {
      first.resolve(snapshot({ pitch: 1 }));
      await earlier;
    });
    expect(result.current.draft.pitch).toBe(9);
  });

  it("serializes settings writes and continues after a failed request", async () => {
    const { result } = await setup();
    const first = deferred<VoiceEngineStatus>();
    mocks.settings.mockReturnValueOnce(first.promise).mockResolvedValueOnce(snapshot({ pass_through: true }));
    let earlier!: Promise<boolean>;
    let later!: Promise<boolean>;
    await act(async () => {
      earlier = result.current.applySettings("first", { pass_through: false });
      later = result.current.applySettings("second", { pass_through: true });
    });
    expect(mocks.settings).toHaveBeenCalledTimes(1);
    await act(async () => {
      first.reject(new Error("first write failed"));
      await earlier;
      await later;
    });
    expect(mocks.settings).toHaveBeenCalledTimes(2);
    expect(result.current.draft.passThrough).toBe(true);
    expect(result.current.error).toBe("");
    expect(result.current.busy).toBe("");
  });

  it("sends one debounced routing patch for a multi-field edit", async () => {
    const { result } = await setup();
    mocks.settings.mockImplementation(async (patch) => snapshot(patch));
    act(() => result.current.updateDraft({ sampleRate: 44100, readChunkSize: 60, extraConvert: 0.8 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });
    expect(mocks.settings).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mocks.settings).toHaveBeenCalledTimes(1);
    expect(mocks.settings).toHaveBeenCalledWith(
      expect.objectContaining({
        server_audio_sample_rate: 44100,
        server_read_chunk_size: 60,
        extra_convert_size: 0.8,
      }),
    );
    expect(result.current.routingApplyState).toBe("applied");
  });

  it("preserves failed routing edits through polling without retrying in a loop", async () => {
    const { result } = await setup();
    mocks.settings.mockRejectedValue(new Error("audio settings unavailable"));
    act(() => result.current.updateDraft({ inputGain: 1.4 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(result.current.routingApplyState).toBe("error");
    await act(async () => {
      await result.current.refresh();
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(result.current.draft.inputGain).toBe(1.4);
    expect(result.current.routingApplyState).toBe("error");
    expect(mocks.settings).toHaveBeenCalledTimes(1);
  });

  it("waits for an in-flight routing write before saving newer routing edits once", async () => {
    const { result } = await setup();
    const first = deferred<VoiceEngineStatus>();
    mocks.settings.mockReturnValueOnce(first.promise).mockImplementation(async (patch) => snapshot(patch));
    act(() => result.current.updateDraft({ inputGain: 1.2 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    act(() => result.current.updateDraft({ inputGain: 1.4 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });
    expect(mocks.settings).toHaveBeenCalledTimes(1);
    await act(async () => {
      first.resolve(snapshot({ server_input_gain: 1.2 }));
    });
    expect(result.current.draft.inputGain).toBe(1.4);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mocks.settings).toHaveBeenCalledTimes(2);
    expect(mocks.settings.mock.calls[1][0]).toMatchObject({ server_input_gain: 1.4 });
    expect(result.current.routingApplyState).toBe("applied");
  });

  it("cancels pending routing debounce when the panel unmounts", async () => {
    const { result, unmount } = await setup();
    act(() => result.current.updateDraft({ outputGain: 0.8 }));
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(mocks.settings).not.toHaveBeenCalled();
  });

  it("finishes already requested commands in order after navigating away", async () => {
    const { result, unmount } = await setup();
    const first = deferred<VoiceEngineStatus>();
    mocks.settings.mockReturnValueOnce(first.promise).mockResolvedValueOnce(snapshot({ pass_through: true }));
    let release!: Promise<boolean>;
    await act(async () => {
      void result.current.applySettings("ptt-down", { pass_through: false });
      release = result.current.applySettings("ptt-up", { pass_through: true });
    });
    unmount();
    await act(async () => {
      first.resolve(snapshot({ pass_through: false }));
      await release;
    });
    expect(mocks.settings).toHaveBeenCalledTimes(2);
    expect(mocks.settings.mock.calls[1][0]).toEqual({ pass_through: true });
  });
});
