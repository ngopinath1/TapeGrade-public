from pathlib import Path
import subprocess
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from sqlalchemy import select

from backend.api.types import Guardrails, ScanRequest
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import (
    Clip,
    GuardrailSettings,
    League,
    JobEvent,
    Player,
    ScanRun,
    ScanReview,
    StagedMove,
    Watchlist,
)
from backend.services.clips import inspect_video, local_path, prepare_clip
from backend.services.state import (
    apply_scoring,
    get_guardrails,
    get_league,
    save_league,
    select_demo,
)
from backend.services.scan_readiness import scan_readiness
from backend.worker.scan import enqueue
from backend.models.base import ModelError
from backend.providers.sleeper import ProviderError, SleeperLeagueProvider
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")
sleeper = SleeperLeagueProvider()


class SleeperRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    season: int | None = Field(None, ge=2017, le=2100)
    league_id: str | None = Field(None, pattern=r"^\d{1,30}$")


@router.post("/sleeper/connect")
def sleeper_connect(value: SleeperRequest):
    try:
        result = sleeper.connect(value.username, value.season, value.league_id)
        if result.get("connected"):
            result["snapshot"] = save_league(result["snapshot"])
        return result
    except ProviderError as e:
        raise HTTPException(422, str(e))


@router.post("/workspace/demo")
def use_demo_workspace():
    select_demo()
    return {"league_id": "demo-nba"}


@router.get("/sleeper/leagues/{league_id}")
def sleeper_league(league_id: str):
    try:
        return sleeper.league(league_id)
    except ProviderError as e:
        raise HTTPException(422, str(e))


@router.post("/sleeper/refresh")
def refresh_sleeper():
    league = get_league()
    connection = league.get("connection") or {}
    if league.get("is_demo", True) or not all(
        connection.get(k) for k in ("user_id", "username", "league_id")
    ):
        raise HTTPException(409, "Connect a Sleeper NBA league before refreshing.")
    try:
        # A fresh client bypasses the in-memory five-minute membership cache.
        provider = SleeperLeagueProvider()
        try:
            snapshot = provider.snapshot_for(
                {"user_id": connection["user_id"], "username": connection["username"]},
                connection["league_id"],
            )
        finally:
            provider.client.close()
        save_league(snapshot)
        return {"saved": True, "fetched_at": snapshot["fetched_at"]}
    except ProviderError as e:
        raise HTTPException(422, str(e))


@router.get("/bootstrap")
def bootstrap():
    league = get_league()
    guards = get_guardrails()
    readiness, _ = scan_readiness(league, guards)
    from backend.services.scan_workflow import workflow_status

    with session_scope() as s:
        ids = {p["id"] for p in league["roster"] + league["available"]}
        watch = [r.player_id for r in s.scalars(select(Watchlist)) if r.player_id in ids]
    return {
        "league": league,
        "settings": guards.model_dump(),
        "scan_readiness": readiness,
        "workflow": workflow_status(league),
        "watchlist": watch,
        "models_mode": "mock" if settings.mock_models else "live",
        "demo_mode": league.get("is_demo", True),
        "scheduler_available": settings.scheduler_enabled,
        "credentials_configured": bool(settings.model_api_key.get_secret_value()),
        "limits": {
            "candidates": settings.max_candidates,
            "retries": settings.max_sam_retries,
            "live_calls": settings.max_live_model_calls_per_scan,
            "clip_seconds": settings.max_clip_seconds,
        },
    }


@router.get("/settings")
def read_settings():
    return get_guardrails()


@router.put("/settings")
def save_settings(value: Guardrails):
    league = get_league()
    roster_ids = {p["id"] for p in league["roster"]}
    if not set(value.protected_players) <= roster_ids:
        raise HTTPException(422, "Protected players must be on the current roster.")
    with session_scope() as s:
        league_row = s.get(League, league["id"])
        next_league = apply_scoring(league_row.data, value.model_dump())
        scoring_changed = next_league["scoring"] != league["scoring"]
        if league.get("is_demo", True):
            s.get(GuardrailSettings, "local").data = value.model_dump()
        else:
            data = {
                **league_row.data,
                "guardrails": value.model_dump(),
                "protections_reviewed": True,
            }
            from backend.services.stat_enrichment import fingerprint

            if scoring_changed and data.get("rules", {}).get("fingerprint") == fingerprint(league):
                data["rules"] = {**data["rules"], "fingerprint": fingerprint(next_league)}
            league_row.data = data
        # A saved recommendation cannot bypass a newly tightened guardrail.
        for row in s.scalars(
            select(ScanRun).where(ScanRun.stage == "COMPLETED", ScanRun.league_id == league["id"])
        ):
            if not row.result or not row.result.get("staged_move"):
                continue
            result = dict(row.result)
            move = dict(result["staged_move"])
            verdict = next(
                c["verdict"]
                for c in result["candidates"]
                if c["player"]["id"] == move["add_player_id"]
            )
            if (
                scoring_changed
                or move["drop_player_id"] in value.protected_players
                or verdict["confidence"] < value.min_confidence
            ):
                result["staged_move"] = None
                result["guardrail_notice"] = (
                    "Recommendation withdrawn after guardrails changed. Run a new scan."
                )
            else:
                if move.get("faab_bid") is not None:
                    move["faab_bid"] = min(move["faab_bid"], value.max_faab_bid)
                result["staged_move"] = move
            row.result = result
            staged = s.scalar(select(StagedMove).where(StagedMove.scan_id == row.id))
            if staged:
                staged.data = result["staged_move"] or {"status": "WITHDRAWN", "executed": False}
    return value


def scan_json(row, review=None):
    return {
        "id": row.id,
        "stage": row.stage,
        "progress": row.progress,
        "instruction": row.instruction,
        "mode": row.mode,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "error": row.error,
        "attempts": row.attempts,
        "live_calls": row.live_calls,
        "source": row.source,
        "result": row.result,
        "action_needed": row.checkpoint.get("recovery"),
        "reviewed": bool(review and review.signature == f"{row.attempts}:{row.stage}"),
    }


@router.get("/scans")
def history():
    league_id = get_league()["id"]
    with session_scope() as s:
        reviews = {
            r.scan_id: r
            for r in s.scalars(
                select(ScanReview).join(ScanRun).where(ScanRun.league_id == league_id)
            )
        }
        return [
            scan_json(r, reviews.get(r.id))
            for r in s.scalars(
                select(ScanRun)
                .where(ScanRun.league_id == league_id)
                .order_by(ScanRun.created_at.desc())
            )
        ]


@router.post("/scans", status_code=202)
def create_scan(value: ScanRequest, idempotency_key: str | None = Header(None)):
    if value.league_id is not None and value.league_id != get_league()["id"]:
        raise HTTPException(
            409, "Selected workspace differs from the requested league. Reload before scanning."
        )
    if not settings.demo_mode and get_league().get("is_demo", True):
        raise HTTPException(
            409,
            "No supported live NBA league provider is configured. Enable DEMO_MODE=1 to use the clearly labeled sample league with mock or live models.",
        )
    if not settings.mock_models and not settings.model_api_key.get_secret_value():
        raise HTTPException(
            409,
            "Live models require MODEL_API_KEY in your backend .env. No simulated fallback was used.",
        )
    if idempotency_key and len(idempotency_key) > 100:
        raise HTTPException(422, "Idempotency key too long.")
    with session_scope() as s:
        active = s.scalar(
            select(ScanRun).where(
                ScanRun.stage.notin_(("COMPLETED", "FAILED")),
                ScanRun.league_id == get_league()["id"],
            )
        )
        if active:
            return {"id": active.id, "existing": True}
    try:
        return {
            "id": enqueue(
                value.instruction,
                request_key=idempotency_key,
                prepare=not settings.mock_models and not get_league().get("is_demo", True),
            )
        }
    except ModelError as e:
        raise HTTPException(409, str(e))


@router.get("/scans/{scan_id}")
def scan_detail(scan_id: str):
    with session_scope() as s:
        row = s.get(ScanRun, scan_id)
        if not row:
            raise HTTPException(404, "Scan not found")
        events = s.scalars(
            select(JobEvent).where(JobEvent.scan_id == scan_id).order_by(JobEvent.id)
        ).all()
        return {
            **scan_json(row, s.get(ScanReview, scan_id)),
            "events": [
                {
                    "id": e.id,
                    "created_at": e.created_at,
                    "stage": e.stage,
                    "actor": e.actor,
                    "message": e.message,
                    "detail": e.detail,
                }
                for e in events
            ],
        }


@router.post("/scans/{scan_id}/review")
def review_scan(scan_id: str):
    league_id = get_league()["id"]
    with session_scope() as s:
        row = s.get(ScanRun, scan_id)
        if not row or row.league_id != league_id:
            raise HTTPException(404, "Scan not found")
        if row.stage not in {"COMPLETED", "FAILED"}:
            return {"reviewed": False}
        signature = f"{row.attempts}:{row.stage}"
        review = s.get(ScanReview, scan_id)
        if review:
            review.signature = signature
        else:
            s.add(ScanReview(scan_id=scan_id, signature=signature))
        return {"reviewed": True}


@router.post("/scans/{scan_id}/retry", status_code=202)
def retry_scan(scan_id: str):
    with session_scope() as s:
        row = s.get(ScanRun, scan_id)
        if not row:
            raise HTTPException(404, "Scan not found")
        if row.stage != "FAILED":
            raise HTTPException(
                409,
                "Only failed scans can be retried; interrupted jobs resume after their lease expires.",
            )
        if row.mode != ("mock" if settings.mock_models else "live"):
            raise HTTPException(409, "Restore the original model mode or start a new scan.")
        if row.checkpoint.get("film_test"):
            from backend.worker.film import retry_film

            try:
                retry_film(scan_id)
            except ModelError as e:
                raise HTTPException(409, str(e))
            return {"id": row.id}
        row.stage, row.error, row.lease_until = "QUEUED", None, 0
        if row.checkpoint.get("automatic_preparation") and not row.checkpoint.get(
            "preparation_done"
        ):
            checkpoint = dict(row.checkpoint)
            checkpoint.pop("stats_refresh_id", None)
            checkpoint.pop("roster_refreshed", None)
            row.checkpoint = checkpoint
        return {"id": row.id}


@router.post("/watchlist/{player_id}")
def watch(player_id: str):
    with session_scope() as s:
        if not s.get(Player, player_id):
            raise HTTPException(404, "Player not found")
        row = s.scalar(
            select(Watchlist).where(Watchlist.user_id == "local", Watchlist.player_id == player_id)
        )
        if row:
            s.delete(row)
            return {"watching": False}
        s.add(Watchlist(user_id="local", player_id=player_id))
        return {"watching": True}


@router.get("/clips")
def clips():
    league_id = get_league()["id"]
    with session_scope() as s:
        return [
            c.data
            for c in s.scalars(
                select(Clip)
                .join(Player, Clip.player_id == Player.id)
                .where(Clip.is_demo == False, Player.league_id == league_id)
                .order_by(Clip.created_at.desc())
            )
        ]


@router.post("/clips", status_code=201)
async def upload_clip(
    file: UploadFile = File(...), player_id: str = Form(...), rights_confirmed: bool = Form(False)
):
    if not rights_confirmed:
        raise HTTPException(422, "Confirm you have rights to process this video.")
    with session_scope() as s:
        if not s.get(Player, player_id):
            raise HTTPException(404, "Unknown player")
    if Path(file.filename or "").suffix.lower() not in (".mp4", ".mov"):
        raise HTTPException(422, "Only MP4 or MOV uploads are supported.")
    directory = settings.data_dir / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    upload = directory / f"{uuid4().hex}.input"
    processed = directory / f"{uuid4().hex}.mp4"
    size = 0
    try:
        with upload.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "Video exceeds the configured upload size limit.")
                out.write(chunk)
        inspect_video(upload)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(upload),
                "-t",
                str(settings.max_clip_seconds),
                "-vf",
                "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2",
                "-r",
                "12",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(processed),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
        return prepare_clip(processed, player_id, False)
    except ValueError as e:
        processed.unlink(missing_ok=True)
        raise HTTPException(422, str(e))
    except subprocess.SubprocessError:
        processed.unlink(missing_ok=True)
        raise HTTPException(422, "Video processing failed. Check the file and ffmpeg installation.")
    finally:
        upload.unlink(missing_ok=True)
        await file.close()


@router.get("/scans/{scan_id}/card")
def card_download(scan_id: str):
    with session_scope() as s:
        run = s.get(ScanRun, scan_id)
        if not run or not run.result or not run.result.get("card"):
            raise HTTPException(404, "Tape Card not available")
        path = local_path(run.result["card"]["url"])
    return FileResponse(path, media_type="image/png", filename=f"tapegrade-{scan_id[:8]}.png")


@router.get("/scans/{scan_id}/evidence")
def evidence_download(scan_id: str):
    from backend.db.schema import ModelCall

    with session_scope() as s:
        run = s.get(ScanRun, scan_id)
        if not run:
            raise HTTPException(404, "Scan not found")
        calls = s.scalars(select(ModelCall).where(ModelCall.scan_id == scan_id)).all()
        events = s.scalars(
            select(JobEvent).where(JobEvent.scan_id == scan_id).order_by(JobEvent.id)
        ).all()
        return JSONResponse(
            {
                "scan": scan_json(run),
                "checkpoint": run.checkpoint,
                "model_calls": [
                    {
                        "model": c.model,
                        "operation": c.operation,
                        "status": c.status,
                        "duration_ms": c.duration_ms,
                    }
                    for c in calls
                ],
                "events": [
                    {"stage": e.stage, "actor": e.actor, "message": e.message, "detail": e.detail}
                    for e in events
                ],
            },
            headers={
                "Content-Disposition": f'attachment; filename="tapegrade-{scan_id[:8]}-evidence.json"'
            },
        )
