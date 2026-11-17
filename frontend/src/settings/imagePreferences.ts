import { createPreferences } from "../lib/preferences";
import {
  DEFAULT_GUIDANCE,
  DEFAULT_SIZE,
  DEFAULT_STEPS,
  inferTouched,
  parseSavedComposer,
  readSaved,
  type SavedComposer,
} from "../components/imageComposerHelpers";

const defaults: Required<SavedComposer> = {
  imgModel: "",
  quantByModel: {},
  negative: "",
  steps: DEFAULT_STEPS,
  guidance: DEFAULT_GUIDANCE,
  width: DEFAULT_SIZE,
  height: DEFAULT_SIZE,
  seed: -1,
  batch: 1,
  count: 1,
  presetId: "",
  selectedLoras: [],
  touched: {},
};

export const imagePreferences = createPreferences("hfabric.preferences.image", defaults, {
  migrate: readSaved,
  parse: (value) => {
    const saved = parseSavedComposer(value);
    return { ...defaults, ...saved, touched: inferTouched(saved) };
  },
});
