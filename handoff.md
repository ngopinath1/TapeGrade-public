# Developer handoff

TapeGrade is a local, single-user React/TypeScript and FastAPI application with
SQLite and a separate persistent worker. Start with `README.md`, `SECURITY.md`,
`docs/API_CONTRACTS.md`, and the provider setup guides.

## Development

```bash
bash scripts/setup.sh
bash scripts/dev-demo.sh
```

The demo needs no accounts or paid model requests. Live operation requires locally
configured provider access and permitted footage; see `.env.example`. Keep keys,
league connections, source media, exports, backups, and runtime reports outside Git.
Do not put account identifiers or machine-specific paths in examples or fixtures.

## Validation

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend audit
```

Python tests use temporary databases/media, block external HTTP, and clear model
credentials. Contract fixtures exercise actual client code without paid requests.
A passing fixture suite does not establish real-world model accuracy.

## Engineering boundaries

- Live and fictional evidence remain visibly distinct. Missing statistics, unknown
  identities, and poor tracks withhold unsupported metrics and recommendations.
- The worker preserves job leases, checkpoints, accumulated model-call limits, and
  completed paid responses across deliberate retries.
- Scoring rules, source freshness, membership, eligibility, protections, roster
  capacity, and position fit gate staged moves. Transactions are never submitted.
- Preserve existing local configuration and runtime data during development.
- Keep the API and frontend on loopback. The request guard is not a multi-user login
  system; public hosting requires a separate authenticated deployment design.

Remaining research includes representative rights-cleared film benchmarks, camera
calibration, action detection, schema migrations, and deployment architecture.
