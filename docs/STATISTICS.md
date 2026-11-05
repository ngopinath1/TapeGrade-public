# Recent statistics and real-league readiness

The local app now has a **League setup** page. It can refresh a configured NBA
statistics source, import a normalized licensed JSON batch, review athlete IDs,
record league-rule evidence, and inspect roster/free-agent game logs. The complete
fictional sample remains available through Connect Sleeper.

## What is implemented

- Provider-neutral Pydantic game records with source references, provider athlete
  and game IDs, season starting year, season type, final/participation status,
  minutes, fetch timestamps, explicit synthetic flags and observed-field coverage.
- A persistent Sleeper-to-statistics crosswalk. Unique shared NBA IDs can link
  automatically; exact normalized names generate review proposals. Punctuation,
  accents and suffixes normalize; collisions stay ambiguous. Team transfers do
  not reject a match. No fuzzy identity assignment.
- An independent, durable refresh queue processed by the existing worker. Date
  windows are at most 30 days. BALLDONTLIE requests use the documented `/v1/stats`
  route, season/date filters and cursor pagination, with page/time caps and no
  automatic HTTP retries. Incomplete refreshes retain the last complete snapshot.
- Game rows upsert by provider/game/athlete; later final-score corrections replace
  older observations. Older arrivals cannot roll back a newer correction. Explicit
  refreshes re-fetch the bounded window for revisions; scans use persisted data
  and never request hundreds of player feeds individually. Refresh is intentionally
  explicit, rather than an automatic background subscription.
- Per-game scoring normalizes turnovers and threes, derives missed shots and
  double/triple doubles, then applies the current saved league weights. Decimal
  arithmetic avoids prematurely rounding per-game values. Enabled unknown rules
  or missing fields produce an unavailable score, with reasons. Personal fouls
  never substitute for technical/flagrant fouls.
- The most recent five observed final games in the declared window are summarized,
  with at least three required for readiness. Previous minutes require five earlier
  games. DNPs and unfinished games are excluded; unknown participation blocks that
  player's readiness. Actual zero statistics remain zero. Exact displayed averages
  can remain visible with stale/synthetic warnings, while readiness stays false.
- Period points remain in `fantasy_points`; `recent_fantasy_average` is a distinct
  field. Both roster and candidate summaries retain sample size, dates, raw game
  fields, scoring events, cache/source references and persistent row IDs.
- Readiness is derived on each snapshot read, with a 24-hour default freshness
  limit. Synthetic inputs never qualify a real league. At least one supported
  candidate and unprotected supported drop must exist. Rule reviews are keyed to
  scoring/settings/season. Scoring-progress markers do not invalidate confirmed rules;
  existing optional protections are preserved for players still on the roster.
- Real jobs reject mock models and freeze their evidence in the checkpoint. A
  deterministic limit narrows the model's input to at most 12 supported candidates
  with usable uploaded clips before Spark shortlists the configured scan count.

## Sportradar NBA source

The Sportradar NBA v8 adapter accepts a locally configured key in the ignored
backend `.env`. Public status exposes key presence only. Obtain appropriate
provider access separately; the app does not create accounts or subscriptions.

Configuration for a bounded trial refresh:

```dotenv
NBA_STATS_PROVIDER=sportradar
SPORTRADAR_API_KEY=
SPORTRADAR_ACCESS_LEVEL=trial
STATS_WINDOW_DAYS=7
STATS_MAX_PAGES=60
STATS_TIMEOUT_SECONDS=180
SPORTRADAR_MIN_INTERVAL_SECONDS=4
```

Never overwrite an existing key with the blank template value.
Restart API and worker after changing configuration. Refresh through League setup.
The request-count and time limits are saved on each queued job, including provider,
access level and pacing. No secrets enter the job checkpoint.

The adapter uses the documented [NBA Schedule](https://developer.sportradar.com/basketball/reference/nba-schedule)
and [Game Summary](https://developer.sportradar.com/basketball/reference/nba-game-summary)
routes with `x-api-key` header authentication. It retrieves each closed game's full
player list once, rather than requesting each athlete individually. It validates
season/year, IDs, completion, Eastern game date, participation and box-score counts.
Sleeper's `sportradar_id` supplies a shared identifier for automatic unambiguous
matches; names alone still require review. Request bodies and auth headers are not
logged. Successful response bodies are hashed and cached with original observation
times and source references.

Trial calls use a conservative four-second gap after each response completes.
Rate-limit failures stop without an automatic HTTP retry or partial snapshot
replacement. Cached schedules expire after ten
minutes; closed-game receipts are rechecked after ten minutes (four hours for older
games) when an explicit refresh needs them. Scans reuse persisted logs.

Sportradar distinguishes `tech_fouls` from `tech_fouls_non_unsportsmanlike`. When the
latter is explicitly zero, technical scoring is unambiguous. A missing subtype or
nonzero non-unsportsmanlike count leaves TF unavailable pending verified Sleeper
semantics. Flagrant fouls map from the player's `flagrant_fouls`; personal/team/coach
fouls never substitute. Raw subtype counts remain in the source receipt.

Explicit inactive/not-playing reasons are recorded as DNPs, excluded from played
game averages and visible as recorded DNP counts. Missing participation without such
evidence remains unknown; it does not count toward the played-game sample size.

The BALLDONTLIE adapter and licensed JSON import remain alternatives. The
[official BALLDONTLIE documentation](https://docs.balldontlie.io/) does not establish
technical/flagrant foul coverage in its game-stat sample; that adapter leaves those
fields missing and cannot independently qualify exact scoring for this league.

For imports, POST a `StatsBatch` JSON to `/api/stats/import`, or use the file picker
in League setup. `/docs` exposes the full schema. Required batch fields are
`provider`, `start_date`, `end_date`, `fetched_at`, `complete`, `source_ref`,
`athletes`, `games` and `synthetic`. Each game identifies its athlete and game,
season/type, status, participation, nullable minutes, box-score fields, fetch time,
source reference and synthetic flag. Use `synthetic: true` for fixtures, including
all fixture games. Only a complete, correctly attributed real feed can qualify.
The upload must cover the whole declared window for the supplied athletes, rather
than a favorable hand-picked subset.

## Rules and transactions

[Sleeper's scoring guide](https://support.sleeper.com/en/articles/4645009-what-scoring-settings-are-available)
confirms double-double/triple-double stacking. Separate 40/50-point stacking still
requires authoritative or known-game evidence. League setup records `stack`,
`highest_only`, or `unknown`; the engine does not assume a default.

[Sleeper's format guide](https://support.sleeper.com/en/articles/4644860-league-formats-game-modes)
explains one counted game per player per week in Lock-In. The app compares per-game
scores; it does not multiply them by scheduled games for weekly value. The actual
connection's numeric enums are not decoded globally. Confirm the league's game
mode, waiver type, season budget and bonus rules in League setup with source
references. A returned budget alone does not establish that FAAB applies.
[Sleeper's waiver guide](https://support.sleeper.com/en/articles/4678615-how-do-faab-and-waivers-work)
describes the distinction between bidding and priority waivers.

Protections are optional user overrides selected in Autopilot. An empty list does
not block recommendations: unprotected players are evaluated from current verified
statistics. Existing explicit selections remain enforced. The current Sleeper
connection has no verified do-not-drop field; it does not infer protections from
roster membership, starters or reserves.

Scan preflight requires supported statistics and an existing usable uploaded clip.
Unknown transaction eligibility allows a **scouting report only** scan. The bootstrap
response and both Scouting desk and League setup show the candidates with film and
the transaction-review notice before inference. Unknown eligibility never produces
an ADD verdict or staged move, even if a model returns ADD without a proposed move.
Final staging checks fresh membership, supported comparable statistics, current
protections, add permission, capacity and a bipartite position assignment. Player
availability and drop/Lock-In locks are not exposed by this public integration.
League setup therefore accepts explicit user-reviewed eligibility evidence with a
source reference, expiring after five minutes; a fresh Sleeper roster refresh is
also required. Unknown eligibility produces no move. Priority/free-agent moves
have `faab_bid: null`; verified FAAB claims require a known remaining budget and
respect the user's cap. No transaction is executed.

In League setup, use **Refresh Sleeper roster** for current roster membership and
rules, then save eligibility for the free agent and the proposed rostered drop in
**Current transaction eligibility**. The drop must have supported recent scores and
fit the position slots after the swap. Run within five minutes of these checks.
**Refresh game logs** is separate: it updates statistics, not waiver status or locks.
Successful setup actions clear stale scan errors. The saved connection refresh uses
a fresh Sleeper client so cached membership is not stamped as newly fetched.

## Film and bounded testing

Structured critic corrections specify a source frame and boxes for every verified
object ID while retaining target/defender/ball roles. They must refer to an inspected
frame and pass bounds checks. Multi-object tracking never follows a target-only
concept retry that would lose those bindings. Numeric metrics still require at
least 75% quality; ADD also requires verified identity, measured references and the
saved confidence threshold. Rejected tracks remain ineligible regardless of other evidence.

A provisional upload with an unknown player identity, date or season cannot
support an ADD. Source footage stays local and is not included in the repository.

The offline real-league contract test first proves synthetic statistics are blocked,
then uses an explicit test-only snapshot patch to exercise all three actual HTTP
clients, a spatial retry, nullable-bid staging and downloads. There is no production
switch permitting synthetic readiness. Eight fixture requests cover that test;
**zero paid requests** occur. Its card is visibly labeled synthetic/offline.

```bash
TAPEGRADE_CONTRACT_ARTIFACT_DIR="$PWD/data/cache/contract-scan" \
  .venv/bin/python -m pytest tests/test_real_contract_scan.py -q
```

Artifacts: ignored `data/cache/contract-scan/tapegrade-offline-contract.png` and
`evidence.json`, referenced media and `tapegrade-offline-contract.zip`. The evidence
includes both fixture players' normalized game rows and retry prompts. Do not
commit exports of a real league: they can reveal membership and provider data.

The live profile remains one candidate, five seconds, six maximum calls, zero SAM
retries and scheduling off. One retry requires two more calls; do not silently
expand the budget. The genuine recommendation test still requires verified named film and current
player availability/lock evidence and source-backed scoring rules.

Every completed scan exposes a PNG attachment and a JSON evidence download containing
the frozen checkpoint, source rows, results, events and model-call ledger. Low-quality
or low-confidence normal outcomes use a local evidence card without paid artwork.
This is an implemented local workflow with external prerequisites, not a claim of
validated current NBA recommendations.


## Source access and evidence

Obtain source access through the provider's official account process. Entitlements,
request quotas, allowed uses and data redistribution rights are account-specific.
The code license does not grant a subscription or rights to provider response data.

Provider receipts and audit reports are kept in ignored `data/cache/`. Connection
identifiers, real-league snapshots, source receipts and SQLite backups are runtime
data. Review evidence exports before sharing them.
