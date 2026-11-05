# API integration notes

Reviewed November 4, 2026 (America/New_York). The exact upstream guides are linked
in README.md. An authenticated model-catalog request listed all three configured
models, and one actual Spark structured-output check passed (700 total tokens).
Subsequently all three clients completed requests for a user-provided four-second
film diagnostic: 48 actual SAM frames, Spark quality 55%, unreliable numerical
metrics withheld, and a real Muse Image background with locally composited labels.
This is not validation of a live fantasy transaction or full-game accuracy.

## Meta

Base origin `https://api.meta.ai`, Bearer credential from backend environment only.

| Client | Path | Request / accepted response |
| --- | --- | --- |
| Spark | POST /v1/chat/completions | model + messages (text / image_url) + response_format.json_schema; choices[0].message.content validated by Pydantic |
| SAM | POST /v1/responses | one message with input_text and input_video.video_url; stream=true; metadata.mask_encoding=one_bit; deltas plus terminal response.completed |
| Image | POST /v1/images/generations | model, prompt, n=1, output_format=png, response_format=b64_json; data[0].b64_json |

SAM media is normalized to H.264 MP4, 960×540, 12 fps and ≤30s. Concept and spatial
prompts are never mixed. The first live call uses verified frame-zero spatial
boxes for target, opposing players and ball when available. Subsequent calls use
the critic's exact revised prompt. Concept ordinals cannot inherit spatial roles.
Source frame markers may be sparse or out of order; outputs are sorted by explicit
index. Meta's parser 0.1.0 supplies Python grammar/mask decoding and prompt building.

Zero matches remains a valid empty tracking result; it produces unavailable metrics.
Malformed or incomplete streams are rejected. No paid inference transport retries
occur automatically. The agent's bounded re-segmentation is distinct from network
retry. Cached successful results are reused across manual job retries.

## Local API

Read the generated OpenAPI spec at `/openapi.json` or `/docs` on port 8000.

| Route | Purpose |
| --- | --- |
| GET /api/health | Health and model/data mode |
| GET /api/bootstrap | League, settings, watchlist, public mode/configuration |
| GET, PUT /api/settings | Persisted and revalidated guardrails |
| POST /api/scans | Enqueue (202); optional Idempotency-Key header; live mode returns 409 before inference when no usable permitted upload exists |
| GET /api/scans | Last 30 scans for the selected league workspace |
| GET /api/scans/{id} | Result, progress and ordered event trail |
| POST /api/scans/{id}/retry | Explicit retry for FAILED run; film diagnostics allow up to two additional calls with a six-total ceiling |
| GET /api/scans/{id}/card | PNG attachment |
| POST /api/watchlist/{player_id} | Toggle watchlist membership |
| GET, POST /api/clips | List uploads / upload multipart file + player_id + rights_confirmed |
| POST /api/sleeper/connect | Username and optional season; adding league_id imports an ownership-verified NBA snapshot and selects that workspace |
| GET /api/sleeper/leagues/{id} | League, rosters and users; observed NBA-by-ID compatibility is labeled separately from NFL discovery |
| POST /api/workspace/demo | Select the preserved sample workspace |
| GET /media/{samples,cache,uploads}/... | Local media only, no database/environment mount |

There is intentionally no execute-transaction route. All local state belongs to a
single local user. Protect/authenticate these endpoints before any remote hosting.

## Sleeper NBA compatibility

Only documented resource paths are used. NBA automatic discovery and undocumented
statistics endpoints are not called. Direct NBA league-ID, roster/user, player-map
and matchup reads were verified on November 4. Returned matchup `players_points`
populate period totals; missing values remain null. This is not a full NBA box-score
feed or a guarantee of upstream NBA support. Player metadata caches on disk for
24 hours, other GET responses in memory for five minutes. A malformed roster or
unmatched owner prevents import. Matchup failures preserve the roster with a warning.

An additive `workspaces` table selects a persisted League. Player IDs include the
provider and league to avoid collisions. Settings, history and watchlist views are
scoped to the league; a queued job reads its original league's guardrails. Connected
NBA scans currently return 409 before model calls because recent candidate statistics
are unavailable. The sample workspace and prior jobs remain available.

## Recent statistics and league reviews

- `GET /api/stats`: current provider availability (never keys), coverage, readiness
  reasons, refresh jobs and identity-review proposals scoped to the active league.
- `POST /api/stats/refresh`: enqueue one bounded provider refresh; returns 202.
  Missing source configuration returns 409 without requesting data.
- `POST /api/stats/import`: validate a normalized `StatsBatch` JSON and enqueue
  its import. Complete pagination/window coverage and explicit provenance are required.
- `POST /api/stats/mappings`: review a current Sleeper athlete/provider athlete
  pair with `sleeper_id`, `athlete_id`, `source_ref`; conflicts return 422.
- `PUT /api/league/rules`: persist source-backed `game_mode` (`lock_in`,
  `game_pick`, `unknown`), `waiver_mode` (`faab`, `priority`, `free_agent`, `unknown`),
  `point_bonus_mode` (`stack`, `highest_only`, `unknown`), optional `faab_budget`,
  and `source_ref`. A confirmed budget must match Sleeper when its value is known.
  Protected-player choices are optional local overrides, not a readiness prerequisite.
- `PUT /api/league/eligibility`: record `player_id`, acquisition status,
  `drop_allowed`, and `source_ref`. Manual evidence expires in five minutes.
- `POST /api/sleeper/refresh`: refresh the selected league's saved connection with
  a new provider client; preserve rule reviews if their fingerprint is unchanged.
  It does not infer current waiver status or Lock-In drop permissions.
- `GET /api/bootstrap` includes `scan_readiness`: blockers, candidate names with
  usable uploads, reviewed add/drop pair count and a report-only notice when
  transaction eligibility is unknown. The same preflight is used when enqueueing.
  Unknown eligibility permits scouting but withholds ADD verdicts and staged moves.
- `GET /api/stats/players/{player_id}`: current sourced recent game evidence and
  distinct reported period points, scoped to the selected league.
- `GET /api/scans/{id}/evidence`: JSON attachment with frozen evidence checkpoint,
  event details, model-call ledger and result. No credentials are included.
- `ScanRequest.league_id` is optional and validates against the active workspace
  when supplied; it is no longer constrained to `demo-nba`. The UI supplies it.
- `ProposedMove.faab_bid` and the rendered staged bid are nullable. Non-FAAB moves
  never invent a bid. Unknown eligibility or budget for a FAAB claim withholds staging.
- `Criticism.retry_objects` and `retry_frame` support validated spatial corrections
  preserving all verified role bindings. No invented defender/ball assignment.

See [STATISTICS.md](STATISTICS.md) for source coverage, freshness and the remaining
live-data prerequisites. No externally sourced fixture can silently enable a real scan.


### Sportradar NBA v8

`NBA_STATS_PROVIDER=sportradar` uses the Schedule and Game Summary REST resources
with header authentication. Provider configuration, request/time caps, window and
post-response spacing are frozen in the refresh job; credentials are not persisted
there. Completed jobs retain a sanitized path/status/time request audit. Failed
refreshes retain audit/call counts and never replace the last complete snapshot.

`Athlete.sportradar_id` enables unique shared-ID mapping. `GameRecord.quality_notes`
records scoring-semantic gaps. Recent player summaries expose actual played sample
size, `recorded_dnp_count` and `unknown_participation_count`. A selected-provider
change invalidates recommendation readiness until a matching snapshot exists.
`last_scored_leg` is scoring progress, not a change to the confirmed league rules.
