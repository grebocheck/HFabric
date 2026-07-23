# Security Policy

HFabric is **pre-release (beta)** software. It is designed as a **local,
single-user** app: by default the backend binds to `127.0.0.1` and nothing is sent
to any cloud service. That design is the first line of defence — but it is not a
substitute for reporting issues.

## Supported versions

This is a fast-moving single-developer project before `1.0`. Only the **latest**
release / `main` is supported; please reproduce on the current version before
reporting.

| Version | Supported |
|---------|-----------|
| latest `0.3.x` / `main` | ✅ |
| older pre-releases | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub's **private vulnerability reporting**:
the repository **Security** tab → **Report a vulnerability**
(<https://github.com/grebocheck/HFabric/security/advisories/new>). This keeps the
report confidential until a fix is available.

Please include:

- what the issue is and the impact (what an attacker could do),
- steps to reproduce or a proof of concept,
- the version / commit and your platform.

Since this is a hobby-scale project, expect a **best-effort** response — typically
an acknowledgement within about a week. There is no bug-bounty program.

## Scope & threat model

HFabric's intended posture (full detail in the
[security model](docs/configuration.md#security-model)):

- The backend binds to `127.0.0.1:8260` by default; the API is not reachable off
  the machine unless you deliberately set `HFAB_HOST=0.0.0.0`.
- A non-loopback bind without `HFAB_API_TOKEN` fails before filesystem, database,
  or subprocess startup. `HFAB_ALLOW_INSECURE_LAN=true` is an explicit dangerous
  opt-in for an isolated trusted network; CORS is **not** authentication.
- Browser media and WebSocket requests use a short-lived HttpOnly, SameSite
  session cookie rather than placing the bearer token in URLs.
- Desktop-reaching actions (e.g. "Show in folder") are **loopback-only regardless
  of token**, so a remote caller can never drive the local desktop.
- Uploads are size/decompression-capped and images are content-validated and
  re-encoded through Pillow. Custom URL downloads reject local/private network
  targets; managed release archives reject traversal, symlinks and oversized
  expansion.

**In scope:** auth/token bypass, the loopback gate on desktop actions, path
traversal in upload/model handling, SSRF, anything that lets a non-local or
unauthenticated caller read files or run code.

**Out of scope:** issues that require the attacker to already have local shell or
filesystem access (this is a local app); the security of third-party **model
weights** you supply (see [MODEL_NOTICE.md](MODEL_NOTICE.md)); and running the app
intentionally exposed on a hostile network without a token.

## Good-faith research

We welcome good-faith testing of a local instance you control. Please don't run
tests against machines or data that aren't yours, and don't include other people's
data in a report.
