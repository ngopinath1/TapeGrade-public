# Security policy

TapeGrade is a local, single-user research application. Start the API and Vite
on loopback using the supplied scripts. The backend rejects non-loopback clients,
unrecognized Host headers, and browser requests from untrusted origins across
API routes, interactive documentation, and media. These checks do not provide
user authentication or isolate different local users.

Do not expose the API, Vite, or media through a public port, reverse proxy, tunnel,
or shared hosting service. Internet hosting needs an authenticated deployment
design, per-user authorization, private media storage, request limits, and a
separate security review. The included development launchers are for local use.

Keep model and statistics keys in the ignored root `.env`. Never put credentials
in React, source URLs, screenshots, exported evidence, or GitHub issues. Uploaded
footage, generated media, provider receipts, SQLite databases, and local backups
stay outside Git. Review exported evidence before sharing it: it can contain
league membership, user instructions, and provider data.

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** on this repository when private
reporting is enabled. Include affected versions, reproduction steps, and impact.
Do not include a live credential or another person's private data. If that option
is unavailable, request a private contact route without posting exploit details
in a public issue. Credential owners should revoke any exposed key immediately.

## Dependency and secret checks

GitHub Actions runs offline tests, builds the frontend, audits both dependency
locks, and scans the complete reachable Git history with redacted Gitleaks output.
Dependabot checks npm, Python, and GitHub Actions updates weekly. Neither the tests
nor CI use live model credentials or make paid model calls.

The code is MIT licensed. Third-party packages retain their own licenses. The code
license grants no rights to NBA broadcasts, publisher videos, data-provider
receipts, team marks, or user uploads. Obtain the necessary permissions separately.
