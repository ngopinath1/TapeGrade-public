# Automatic live scanning

The normal app flow is connect Sleeper, run a scan, review the report. Per-player uploads and manual game-log refreshes are no longer scan prerequisites.

## What runs automatically

1. The API records a durable live scan with the selected league ID and the existing call limit.
2. The worker refreshes that league’s roster, available players and settings through Sleeper. It does not change the user’s selected workspace if they switch pages or leagues.
3. Recent game logs are reused within the configured freshness window, or refreshed through the configured statistics provider. Partial, failed, stale and synthetic batches cannot qualify real comparisons. Source timestamps remain visible.
4. Muse Spark shortlists players from supported current comparisons. The worker searches existing permitted uploads and the authorized footage catalog, preferring available film among comparable fits.
5. Missing film triggers bounded, cached player-specific ESPN metadata discovery. When the user enables public-source private analysis, a matching direct public ESPN MP4 is downloaded and prepared as a short excerpt with source attribution and game date. The excerpt still requires visual identity and tracking checks. With this option off, or when media access fails, source links remain viewing links and do not supply measurements.
6. Available permitted video is checked with the actual Spark/SAM clients. If identity, tracking or supported measurements are unclear, the scan automatically tries a different eligible clip within the remaining budget. Identity uncertainty and poor tracking withhold metrics and moves. Image generation is skipped when the evidence or remaining budget does not qualify.
7. Final transaction checks still validate current membership, locks, protections and limits. Unknown acquisition/drop eligibility does not become permission to recommend an executable transaction.

The visible stages are Refresh league → Update scores → Find players → Find footage → Check film → Build report. Errors retain completed work. A deliberate retry of a failed preparation can refresh data again, while paid model caches and the scan’s accumulated call count remain intact.

## Server setup

Use the existing `MODEL_API_KEY` and statistics provider credentials in ignored `.env`. Start `bash scripts/dev-live.sh`. Its one-candidate, six-call, five-second profile remains bounded and scheduling stays off. The explicit `scripts/dev-demo.sh` is the simulated alternative.

`STATS_AUTO_REFRESH_MINUTES=60` controls refresh frequency; it does not relax statistical readiness, sample-size or transaction gates. The existing provider request, time and pacing limits remain enforced. Interrupted refreshes are not automatically replayed as successful data.

## An authorized footage library

A library can supply local files or direct HTTPS media from explicitly allowed hosts. Configure it once, then scans match and prepare clips automatically using the shared NBA player ID and a recent game date.

```dotenv
FOOTAGE_CATALOG_PATH=/absolute/path/to/catalog.json
FOOTAGE_MEDIA_ROOT=/absolute/path/to/permitted-media
FOOTAGE_ALLOWED_HOSTS=["media.your-licensed-provider.example"]
FOOTAGE_MAX_AGE_DAYS=7
FOOTAGE_DISCOVERY_ENABLED=1
```

The catalog is a JSON array. For example:

```json
[
  {
    "nba_id": "1630573",
    "game_date": "2026-11-01",
    "title": "Player-specific possession",
    "source_ref": "https://your-provider.example/original-source",
    "rights_reference": "Your source agreement permitting local and model analysis",
    "path": "permitted-game.mp4",
    "start_seconds": 58,
    "duration_seconds": 4
  }
]
```

Use `url` instead of `path` for a direct HTTPS video file. Only configured hosts are requested; private network addresses, redirects and oversized downloads are rejected. Local paths must remain inside the library root. Processing uses a bounded excerpt, strips audio, retains source/date/rights provenance and leaves identity pending until visual verification. Historical or future-dated catalog entries cannot qualify as current film. Do not put credentials in source references or browser-visible metadata.

The catalog adapter does not create subscriptions or acquire media rights. User-enabled public-source analysis is separate:

```dotenv
PUBLIC_FOOTAGE_ANALYSIS_ENABLED=1
```

This option records the user's choice to analyze public highlights privately, without describing that choice as a publisher license. Direct public ESPN MP4 links are supported. Authentication, geographic restrictions, DRM and rate-limit responses are not bypassed. Public metadata lookup reads official ESPN schedule and game-summary JSON, requires exact full-name references, limits requests and caches responses for 30 minutes. Metadata-only mode does not download video.

YouTube, Twitter/X and Reddit clips require separate source access and permission. This implementation currently retrieves matching ESPN publisher files directly, rather than depending on social reuploads or downloading irrelevant weekly compilations. There is no claim of a comprehensive YouTube/X/Reddit search adapter.

## Validation and limitations

Offline coverage exercises automatic enqueue, refresh ordering, source failures,
freshness, workspace isolation, targeted refresh jobs, exact athlete matching,
source provenance, local excerpt extraction, and all three actual HTTP clients.
These tests use fixtures and do not establish model accuracy on live games.

Named reviews select the requested player without a preliminary scouting call.
Every readable player is joined to a unique dated roster/statistics identity;
ambiguous joins remain unresolved. Quality review preserves object roles and
withholds unreliable tracks. Failed clips can trigger an alternative within the
same accumulated call budget, reserving capacity for the final report. Duplicate
frames and overlapping source spans cannot count as independent footage.

Per-player profiles retain separate source rows, sample sizes, league membership,
identity and tracking checks. Another team's rostered player stays trade research.
The final decision uses each candidate's own qualified evidence and current
transaction guardrails. Missing evidence does not become a successful ADD.

Private verification reports, provider receipts, connection details, and media
remain in ignored runtime directories. No source video or real-league export is
included in the repository. Review exports and recordings before sharing them.
