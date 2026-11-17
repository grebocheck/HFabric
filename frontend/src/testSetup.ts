import { beforeEach } from "vitest";

// Each test starts with a fresh browser profile. Individual persistence tests
// deliberately remount/reload inside the test to retain that profile.
beforeEach(() => localStorage.clear());
