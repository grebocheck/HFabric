import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import {
  DEFAULT_IMAGE_SETTINGS,
  mergeImageDefaultSettings,
  type ImageDefaultSettings,
} from "./imageComposerHelpers";

export function useImageDefaultSettings(): ImageDefaultSettings {
  const [defaults, setDefaults] = useState<ImageDefaultSettings>(DEFAULT_IMAGE_SETTINGS);

  const refresh = useCallback(() => {
    void api
      .settingsOverrides()
      .then(({ values }) => {
        if (!values || typeof values !== "object") return;
        setDefaults(mergeImageDefaultSettings(values));
      })
      .catch((error: unknown) => {
        console.warn("Could not load server image defaults", error);
      });
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener("hfabric:settings-overrides", refresh);
    return () => window.removeEventListener("hfabric:settings-overrides", refresh);
  }, [refresh]);

  return defaults;
}
