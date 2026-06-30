# First-Run Audit Checklist

Use this checklist for the P24.7 clean Windows tester pass. The goal is to prove
that a new tester can go from a fresh checkout or release zip to a working STUB
session, a verified REAL profile, and clear recovery paths when something is
missing or blocked.

Do not run this on an already-tuned developer checkout and call it done. The
useful signal comes from a clean machine, or at least a clean Windows user profile
with no existing `.tools`, `.venv`, `frontend/node_modules`, `data`, or `models`
directories in the checkout.

## Tester Machine

Record these before setup:

| Field | Value |
| --- | --- |
| Date |  |
| Tester |  |
| Source | release zip / fresh clone |
| Windows version |  |
| GPU and VRAM |  |
| NVIDIA/AMD driver |  |
| System RAM |  |
| Free disk before setup |  |
| Network constraints |  |

## Clean Checkout

1. Start from a fresh source zip or clone.
2. Confirm these paths do not exist in the checkout:
   - `.tools`
   - `.venv`
   - `frontend/node_modules`
   - `data`
   - `models`
3. Open a normal terminal, not an already-activated Python or Node shell.
4. Capture the pre-setup snapshot:

   ```powershell
   python scripts/first_run_audit.py --phase pre --fail-on-blockers --output first-run-pre.md
   ```

Expected result: the repo contains source files only, and setup has to bootstrap
the managed Python/Node/runtime pieces itself. The snapshot `Assessment` should
read `PASS`; `FAIL` means this was not captured from a clean checkout or the
source tree is incomplete.

## Setup

Run:

```powershell
setup.bat
```

Record:

- Final exit code.
- Whether managed Python was downloaded or reused.
- Whether managed Node.js/npm was downloaded or reused.
- Whether the backend venv was created.
- Whether frontend dependencies installed.
- Any warning or retry prompt.

Capture the post-setup snapshot:

```powershell
.\.venv\Scripts\python.exe scripts\first_run_audit.py --phase post-setup --fail-on-blockers --output first-run-post-setup.md
```

Pass criteria:

- Setup finishes without manual PATH edits.
- `.\.venv\Scripts\python.exe --version` prints Python 3.12.x.
- `.\.tools\node-v*-win-x64\npm.cmd --version` or `npm.cmd --version` works
  through the project-managed Node path.

## STUB First Launch

Run:

```powershell
run.bat stub
```

In the browser:

1. Confirm the app opens on loopback.
2. Confirm the STUB-mode banner is visible and dismissible.
3. Confirm the Welcome modal appears for a fresh profile and can be dismissed.
4. Open Images and queue one STUB image job.
5. Open Video and queue one STUB video job.
6. Open History and confirm both outputs are visible.
7. Refresh the browser and confirm the app recovers.

Capture the post-STUB snapshot:

```powershell
.\.venv\Scripts\python.exe scripts\first_run_audit.py --phase post-stub --fail-on-blockers --output first-run-post-stub.md
```

Pass criteria:

- No ML stack or GPU model weights are required.
- Jobs progress over the WebSocket and finish.
- Generated assets are served from local URLs only.
- No console or backend exception leaves the UI permanently spinning.

## REAL Profile Verification

Stop STUB mode and run:

```powershell
.\.venv\Scripts\python.exe scripts\install_smoke.py
```

Paste the full `Installer profile smoke` block into `docs/gpu-smoke.md` or the
test report.

Pass criteria:

- `Overall: PASS`.
- `torch_visible` matches the selected profile.
- `feature_sanity` is PASS.
- `video_policy` is PASS.
- The verify snippet reports the expected accelerator.

## REAL First Launch

Run:

```powershell
run.bat
```

In the browser:

1. Open System -> Setup Doctor.
2. Confirm the selected profile, tier, feature badges, and warning text match
   the `install_smoke.py` result.
3. Open Models -> Downloads and confirm recommended items match the active
   profile.
4. Use the disk preflight before starting any large download.
5. If starter weights are already available, queue one small real image job.

Capture the post-REAL snapshot:

```powershell
.\.venv\Scripts\python.exe scripts\first_run_audit.py --phase post-real --fail-on-blockers --output first-run-post-real.md
```

Pass criteria:

- Model compatibility warnings are visible before queueing.
- Missing model weights produce a friendly nudge, not a crash.
- A load failure clears the spinner and keeps the app usable.
- RAM/VRAM telemetry updates in System.

## Resilience Drills

Run only the drills that are safe for the tester machine. Record skipped drills
with a reason.

| Drill | Command / action | Expected behavior | Result |
| --- | --- | --- | --- |
| Port conflict | Start a dummy process on the frontend or backend port, then run `run.bat stub`. | Launcher reports or resolves the conflict without a silent hang. |  |
| Missing frontend deps | Rename `frontend/node_modules`, then run `run.bat stub`. | Launcher repairs dependencies or gives a clear setup instruction. |  |
| Missing backend package | Rename `.venv`, then run `run.bat stub`. | Launcher rebuilds/repairs the venv. |  |
| Model load failure | Point a model entry at a missing file or try an unavailable model. | Queue rejects or job fails with a friendly compatibility/load message. |  |
| Disk pressure | Attempt a model download with insufficient free disk, if practical. | Download preflight refuses before partial large writes. |  |

## Artifacts To Attach

Attach or paste:

- The `setup.bat` tail showing success or the exact failure.
- The `first-run-*.md` snapshots from `scripts/first_run_audit.py`, each with
  `Assessment: PASS` or an explained warning.
- The `install_smoke.py` summary block.
- A screenshot of Setup Doctor.
- A screenshot of Model Downloads recommendations.
- Backend log lines for any failure.
- The exact command used for every failed drill.

## Result

Use one of:

- PASS: clean setup, STUB launch, REAL profile smoke, and safe selected drills
  all passed.
- PASS WITH NOTES: core flow passed, but a non-blocking warning or skipped drill
  needs follow-up.
- FAIL: setup, launch, profile verification, or a recovery path blocked the tester.

When this checklist passes on a clean tester Windows machine, update
`ROADMAP.md` P24.7 and add a dated note to the validation section of the next
audit snapshot.
