import { useEffect, useRef, useState } from "react";
import { Crosshair, Eye, EyeOff, Maximize2, Pause, Play } from "lucide-react";
import type { Candidate } from "../types";
import { PlayerIdentity } from "./PlayerIdentity";
import { IdentifiedPlayers } from "./IdentifiedPlayers";
import { ClipAttempts } from "./ClipAttempts";

const colors = {
  target: "#bcf87a",
  defender: "#83b7f4",
  ball: "#ffba72",
  unknown: "#c7c7c7",
};
export function FilmPlayer({ candidate }: { candidate?: Candidate }) {
  const video = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const trackingAccepted =
    candidate?.tracking_accepted ?? (candidate?.quality ?? 0) >= 0.75;
  const tracking = candidate?.reviewed_tracking ?? candidate?.tracking;
  const sceneOnly = candidate?.tracking_review?.scene_only === true;
  const reviewedObjects = Boolean(
    candidate?.reviewed_tracking?.frames.some((frame) => frame.objects.length),
  );
  useEffect(() => {
    setTime(0);
    setPlaying(false);
    setOverlay(trackingAccepted || reviewedObjects);
  }, [
    candidate?.player.id,
    candidate?.clip?.id,
    trackingAccepted,
    reviewedObjects,
  ]);
  useEffect(() => {
    if (!playing) return;
    let request: number;
    const tick = () => {
      if (video.current) setTime(video.current.currentTime);
      request = requestAnimationFrame(tick);
    };
    request = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(request);
  }, [playing]);
  const frames = tracking?.frames ?? [];
  const roles = new Set(
    frames.flatMap((frame) => frame.objects.map((object) => object.role)),
  );
  const nearest = frames.length
    ? frames.reduce((a, b) =>
        Math.abs(a.time - time) < Math.abs(b.time - time) ? a : b,
      )
    : undefined;
  const observed =
    nearest &&
    Math.abs(nearest.time - time) <=
      (tracking?.simulated ? 0.26 : 0.51 / (tracking?.fps ?? 12))
      ? nearest
      : undefined;
  const clip = candidate?.clip;
  const seek = (value: number) => {
    if (video.current) {
      video.current.currentTime = value;
      setTime(value);
    }
  };
  return (
    <section className="film-panel">
      <div className="film-title">
        <div>
          <h2>{candidate?.player.name ?? "Player film"}</h2>
          <p>
            {candidate
              ? `${candidate.player.team}${candidate.player.number === null ? "" : ` · #${candidate.player.number}`} · ${candidate.player.positions.join(" / ")}`
              : "Run a scan to open the film report."}
          </p>
        </div>
        <span
          className={`verification-status ${(candidate?.identity ? candidate.identity.status === "corroborated" : candidate?.verified) ? "verified" : ""}`}
        >
          {candidate?.identity
            ? candidate.identity.status === "corroborated"
              ? "Identity corroborated"
              : candidate.identity.status === "tracking_rejected"
                ? "Tracking identity uncertain"
                : "Identity unconfirmed"
            : candidate?.verified
              ? "Clip verified"
              : candidate
                ? "Clip unverified"
                : "No player selected"}
        </span>
      </div>
      {candidate && (
        <div className="player-assessment">
          <p>{candidate.verdict.rationale}</p>
          <span>
            {Math.round(candidate.verdict.confidence * 100)}% verdict confidence
            {candidate.player.minutes !== null &&
              candidate.player.previous_minutes !== null &&
              ` · ${candidate.player.minutes - candidate.player.previous_minutes >= 0 ? "+" : ""}${(candidate.player.minutes - candidate.player.previous_minutes).toFixed(1)} minutes vs. previous`}
          </span>
        </div>
      )}
      <div className="film-source">
        {tracking?.simulated
          ? "Original schematic film · simulated tracking"
          : clip
            ? clip.public_source
              ? "Public ESPN highlight"
              : "Uploaded footage"
            : "No footage available"}
      </div>
      {clip && !clip.is_demo && (
        <p className="film-provenance">
          {clip.source_ref?.startsWith("https://") ? (
            <a href={clip.source_ref} target="_blank" rel="noreferrer">
              {clip.source_title ?? clip.source}
            </a>
          ) : (
            clip.source
          )}
          {" · "}
          {clip.game_date
            ? `Game date: ${clip.game_date}`
            : "Game date not supplied"}
          {" · "}
          {clip.duration.toFixed(1)}s excerpt
          {clip.source_span
            ? ` · source ${clip.source_span.start.toFixed(1)}–${clip.source_span.end.toFixed(1)}s`
            : ""}
        </p>
      )}
      <ClipAttempts candidate={candidate} />
      <PlayerIdentity candidate={candidate} />
      {sceneOnly && (
        <p className="verification-note" role="status">
          Visible players are tracked without names. The requested player’s
          identity is unconfirmed, so these scene tracks do not support their
          fantasy measurements or a roster move.
        </p>
      )}
      {tracking && !trackingAccepted && !sceneOnly && !reviewedObjects && (
        <p className="verification-note" role="status">
          Tracking needs review ({Math.round((candidate?.quality ?? 0) * 100)}%
          quality). Film measurements were withheld. Overlays are hidden; use
          the eye button to inspect the unreliable tracks.
        </p>
      )}
      {candidate && clip && !frames.some((frame) => frame.objects.length) && (
        <p className="verification-note" role="status">
          No reliable player tracks are available for this clip.{" "}
          {candidate.verification?.reason ??
            "The clip did not pass the detection and identity checks."}
        </p>
      )}
      <div className="video-wrap">
        {clip ? (
          <>
            <video
              key={clip.id}
              ref={video}
              src={clip.url}
              playsInline
              preload="auto"
              muted
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onEnded={() => setPlaying(false)}
              aria-label={`Analyzed clip for ${candidate?.player.name}`}
            />
            {tracking && overlay && observed && (
              <svg
                className="tracking-overlay"
                viewBox={`0 0 ${tracking.width} ${tracking.height}`}
                preserveAspectRatio="xMidYMid meet"
                aria-label="Segmentation and bounding box overlay"
              >
                {observed.objects.map((o) => (
                  <g key={o.id}>
                    {o.mask_url && (
                      <image
                        href={o.mask_url}
                        x={o.box[0]}
                        y={o.box[1]}
                        width={o.box[2] - o.box[0] + 1}
                        height={o.box[3] - o.box[1] + 1}
                        opacity=".38"
                        preserveAspectRatio="none"
                      />
                    )}
                    {o.mask_polygon && (
                      <polygon
                        points={o.mask_polygon
                          .map((p) => p.join(","))
                          .join(" ")}
                        fill={colors[o.role]}
                        fillOpacity=".24"
                      />
                    )}
                    <rect
                      x={o.box[0]}
                      y={o.box[1]}
                      width={Math.max(0, o.box[2] - o.box[0])}
                      height={Math.max(0, o.box[3] - o.box[1])}
                      fill="none"
                      stroke={colors[o.role]}
                      strokeWidth="2"
                    />
                    <text
                      x={o.box[0]}
                      y={Math.max(15, o.box[1] - 8)}
                      fill={colors[o.role]}
                      fontSize="13"
                      fontFamily="monospace"
                    >
                      {trackingAccepted &&
                      candidate?.identity?.status === "corroborated"
                        ? (candidate.identity.tracked_players.find(
                            (p) => p.object_id === o.id,
                          )?.name ??
                          `${o.role === "unknown" ? "PLAYER" : o.role.toUpperCase()} ${o.id}`)
                        : `${o.role === "unknown" ? "PLAYER" : o.role.toUpperCase()} ${o.id}`}
                    </text>
                    <circle
                      cx={o.centroid[0]}
                      cy={o.centroid[1]}
                      r="3"
                      fill={colors[o.role]}
                    />
                  </g>
                ))}
              </svg>
            )}
            <div className="film-bug">
              <span className="live-dot" />
              {tracking
                ? tracking.simulated
                  ? "SIMULATED TRACKS"
                  : reviewedObjects && sceneOnly
                    ? "SCENE TRACKS · IDENTITY UNCONFIRMED"
                    : trackingAccepted
                      ? "SAM 3.1 TRACKS"
                      : overlay
                        ? "UNRELIABLE TRACKS · FOR INSPECTION"
                        : "TRACKING WITHHELD"
                : "NO ACCEPTED TRACKS"}
            </div>
          </>
        ) : (
          <div className="film-empty">
            <Crosshair size={24} />
            <span>No clip analyzed yet</span>
          </div>
        )}
      </div>
      <div className="film-controls">
        <button
          className="icon-button"
          aria-label={playing ? "Pause clip" : "Play clip"}
          title={playing ? "Pause clip" : "Play clip"}
          disabled={!clip}
          onClick={() => {
            if (playing) video.current?.pause();
            else video.current?.play().catch(() => {});
          }}
        >
          {playing ? <Pause size={17} /> : <Play size={17} />}
        </button>
        <span className="timecode">
          {time.toFixed(1)} / {clip?.duration.toFixed(1) ?? "0.0"}s
        </span>
        <input
          aria-label="Clip timeline"
          type="range"
          min="0"
          max={clip?.duration ?? 1}
          step="0.05"
          value={time}
          onChange={(e) => seek(Number(e.target.value))}
          disabled={!clip}
        />
        <button
          className="icon-button"
          aria-label="Toggle segmentation overlays"
          title={overlay ? "Hide tracking overlays" : "Show tracking overlays"}
          aria-pressed={overlay}
          disabled={!tracking}
          onClick={() => setOverlay((v) => !v)}
        >
          {overlay ? <Eye size={16} /> : <EyeOff size={16} />}
        </button>
        <button
          className="icon-button"
          aria-label="Full screen clip"
          title="Full screen clip"
          disabled={!clip}
          onClick={() => {
            void video.current?.requestFullscreen?.().catch(() => {});
          }}
        >
          <Maximize2 size={15} />
        </button>
      </div>
      <div className="film-legend">
        {roles.has("target") && (
          <span>
            <i style={{ background: colors.target }} />
            Target player
          </span>
        )}
        {roles.has("defender") && (
          <span>
            <i style={{ background: colors.defender }} />
            Defenders
          </span>
        )}
        {roles.has("ball") && (
          <span>
            <i style={{ background: colors.ball }} />
            Basketball
          </span>
        )}
        {roles.has("unknown") && (
          <span>
            <i style={{ background: colors.unknown }} />
            Unidentified players
          </span>
        )}
        <span className="muted">
          {frames.length
            ? `${frames.length} observed frames`
            : "Screen-space tracking"}
        </span>
      </div>
      {clip && (
        <p className="tracking-coverage">
          {roles.has("target") ? "Target tracked" : "Target not identified"}
          {" · "}
          {roles.has("defender")
            ? "Opposing players tracked"
            : "No confirmed defender tracks"}
          {" · "}
          {roles.has("ball") ? "Basketball tracked" : "Basketball not tracked"}
        </p>
      )}
      {candidate && !candidate.verified && !candidate.identity && (
        <p className="verification-note">
          {candidate.verification
            ? `Clip rejected: ${candidate.verification.reason}`
            : "No permitted clip available. Upload clearly identified footage in the Film library."}
        </p>
      )}
      <div className="film-metrics">
        {candidate ? (
          candidate.metrics.map((m) => (
            <div key={m.name} title={m.description}>
              <span>{m.label}</span>
              <strong>
                {m.value === null ? (
                  <span className="unavailable">Unavailable</span>
                ) : (
                  <>
                    {m.value}
                    <small>{m.unit}</small>
                  </>
                )}
              </strong>
              <p>
                {m.value === null
                  ? m.unavailable_reason
                  : `${Math.round(m.confidence * 100)}% quality · ${m.evidence_frames.length} observations`}
              </p>
            </div>
          ))
        ) : (
          <div className="metric-empty">
            Film measurements appear after analysis. Choose another candidate to
            inspect available footage.
          </div>
        )}
      </div>
      <IdentifiedPlayers profiles={candidate?.identified_players} />
      {candidate && (
        <details className="method-note">
          <summary>How these film proxies are measured</summary>
          {candidate.metrics.map((m) => (
            <p key={m.name}>
              <b>{m.label}:</b> {m.description}{" "}
              {m.evidence_frames.length > 0 &&
                `Source frames: ${m.evidence_frames.join(", ")}.`}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
