# Implementation status

TapeGrade provides a complete fictional demonstration and an implemented live
integration path. Real-world recommendation accuracy remains unvalidated.

## Implemented

- React/Vite workspace with sample/live distinctions, roster, scouting, film,
  settings, source evidence, scan history, and PNG/JSON exports.
- FastAPI, SQLAlchemy/SQLite, and a separate durable worker with leases,
  checkpoints, idempotency, bounded model calls, and manual recovery.
- Muse Spark structured reasoning, SAM segmentation, and Muse Image artwork
  clients, plus deterministic mock models and offline HTTP contract fixtures.
- Identity verification, tracking criticism, bounded corrections, alternate-clip
  selection, source-span deduplication, and explicit withholding of failed metrics.
- Sleeper roster import, independent Sportradar/BALLDONTLIE statistics adapters,
  licensed JSON import, exact scoring and source-backed rule/eligibility review.
- Guarded staged recommendations with current membership, lock, position-fit,
  confidence, FAAB, and protected-player checks. No transaction execution endpoint.
- Optional authorized footage catalogs and explicit public-highlight analysis;
  metadata-only source links are never presented as analyzed film.
- Local-only request protection, MIT licensing, dependency audits, redacted
  history scanning, and proposed GitHub Actions/Dependabot configuration.

## Validation

Run the commands in `handoff.md`. Tests isolate databases/media and block external
HTTP. Fixtures validate software behavior without paid inference. Live credentials,
provider responses, media, backups, account details, and private verification
reports are intentionally absent from this repository.

## Limitations

Film measurements are screen-space proxies, not calibrated official tracking.
Unclear player identity or poor tracks cannot support numeric film evidence.
Unknown eligibility prevents an ADD or staged move. No current sports-data or
video rights are supplied by the source-code license. Scheduling requires the
local machine and worker to stay awake; it defaults off.

Public hosting, authentication, multi-user authorization, distributed storage,
versioned database migrations, notification delivery, and fantasy transaction
execution are outside the current application. See `SECURITY.md` before hosting.
