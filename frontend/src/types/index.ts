export type Player = {
  id: string;
  name: string;
  team: string;
  positions: string[];
  minutes: number | null;
  previous_minutes: number | null;
  fantasy_points: number | null;
  trend: number[];
  number: number | null;
  source: string;
  is_demo: boolean;
  film_only?: boolean;
  external_id?: string;
  lineup_status?: string;
  injury_status?: string | null;
  stats: Record<string, number>;
  recent_fantasy_average?: number | null;
  recent?: {
    ready: boolean;
    sample_size: number;
    recorded_dnp_count?: number;
    unknown_participation_count?: number;
    window_start: string;
    window_end: string;
    provider: string;
    fetched_at: string;
    reasons: string[];
    games: {
      row_id: string;
      game_id: string;
      date: string;
      minutes: number | null;
      score: number | null;
      source_ref: string;
      coverage: string[];
    }[];
  };
};
export type Guardrails = {
  min_confidence: number;
  max_faab_bid: number;
  protected_players: string[];
  schedule_enabled: boolean;
  pre_waiver_hour: number | null;
  scoring_weights?: Record<string, number> | null;
};
export type League = {
  id: string;
  name: string;
  team_name: string;
  standing: string;
  record: string;
  faab_remaining: number | null;
  is_demo?: boolean;
  season?: string;
  provider?: string;
  period?: number | null;
  period_points?: number | null;
  points_warning?: string | null;
  scoring?: { type: string; weights: Record<string, number> };
  connection?: {
    username: string;
    league_id: string;
    user_id: string;
    roster_id: number;
  };
  fetched_at?: string;
  compatibility?: string;
  scouting_ready?: boolean;
  scouting_unavailable_reason?: string;
  readiness_reasons?: string[];
  protections_reviewed?: boolean;
  rules?: {
    game_mode?: string;
    waiver_mode?: string;
    point_bonus_mode?: string;
    source_ref?: string;
    faab_budget?: number | null;
  };
  rule_settings?: Record<string, unknown>;
  stats_coverage?: { ready_candidates: number; ready_drops: number };
  roster: Player[];
  available: Player[];
  notice: string;
};
export type Bootstrap = {
  workflow?: {
    automatic: boolean;
    can_start: boolean;
    blockers: string[];
    footage_configured: boolean;
    footage_discovery_enabled: boolean;
    public_footage_analysis_enabled?: boolean;
    stats_updated_at: string | null;
    roster_updated_at: string | null;
  };
  scan_readiness?: {
    ready: boolean;
    blockers: string[];
    notice: string | null;
    eligible_pair_count: number;
    candidates: {
      id: string;
      name: string;
      eligible_drop_ids: string[];
      transaction_issues: string[];
    }[];
  };
  league: League;
  settings: Guardrails;
  watchlist: string[];
  models_mode: "mock" | "live";
  demo_mode: boolean;
  scheduler_available: boolean;
  credentials_configured: boolean;
  limits: {
    candidates: number;
    retries: number;
    live_calls: number;
    clip_seconds?: number;
  };
};
export type Metric = {
  name: string;
  label: string;
  value: number | null;
  unit: string;
  confidence: number;
  description: string;
  evidence_frames: number[];
  unavailable_reason: string | null;
};
export type TrackedObject = {
  id: number;
  role: "target" | "defender" | "ball" | "unknown";
  box: number[];
  centroid: number[];
  mask_url: string | null;
  mask_polygon: number[][] | null;
};
export type Tracking = {
  width: number;
  height: number;
  fps: number;
  simulated: boolean;
  prompt: string;
  frames: { frame: number; time: number; objects: TrackedObject[] }[];
};
export type Clip = {
  source_span?: { start: number; end: number };
  source_ref?: string;
  source_title?: string;
  game_date?: string;
  public_source?: boolean;
  subject_name?: string;
  id: string;
  player_id: string;
  url: string;
  is_demo: boolean;
  duration: number;
  width: number;
  height: number;
  fps: number;
  frames: { time: number; frame: number; url: string }[];
  source: string;
};
export type Verdict = {
  player_id: string;
  verdict: "ADD" | "MONITOR" | "PASS";
  confidence: number;
  rationale: string;
  strengths: string[];
  weaknesses: string[];
  metric_refs: string[];
};
export type Critique = {
  attempt: number;
  clip_attempt?: number;
  tracking_attempt?: number;
  quality_score: number;
  identity_swaps: string[];
  retry_justified: boolean;
  refined_prompt: string;
  explanation: string;
  prompt: string;
};
export type ObservedPlayerProfile = {
  id: string;
  object_id: number;
  name: string;
  team: string;
  jersey_number: string;
  espn_id: string;
  stats_player_id: string | null;
  league_player_id: string | null;
  availability: "available" | "your_roster" | "rostered_elsewhere" | "unknown";
  roster_source: string | null;
  game_date: string | null;
  match_status: string;
  statistics: {
    ready: boolean;
    fresh: boolean;
    synthetic: boolean;
    provider: string;
    fetched_at: string;
    window_start: string;
    window_end: string;
    sample_size: number;
    fantasy_per_game: number | null;
    minutes_per_game: number | null;
    averages: Record<string, { value: number | null; sample_size: number }>;
    games: {
      date: string;
      minutes: number | null;
      score: number | null;
      stats: Record<string, number>;
      source_ref: string;
    }[];
    reasons: string[];
  } | null;
  film: {
    quality: number;
    accepted: boolean;
    identity_continuity_confirmed: boolean;
    notice: string;
    metrics: Metric[];
  };
  recommendation: {
    verdict: string;
    rationale: string;
    source: string;
    confidence?: number;
  };
};
export type Candidate = {
  reviewed_tracking?: Tracking;
  tracking_review?: {
    scene_only: boolean;
    quality_by_id: Record<string, number>;
    trusted_object_ids: number[];
    target_quality: number;
    issues: string[];
    roles: Record<"target" | "defender" | "ball" | "unknown", number>;
  };
  clip_attempts?: {
    source_span?: { start: number; end: number } | null;
    number: number;
    clip_id: string | null;
    source_ref: string | null;
    source_title: string | null;
    game_date: string | null;
    quality: number;
    outcome: string;
    reason: string;
    selected: boolean;
  }[];
  clip_fallback?: {
    same_highlight_excerpts?: boolean;
    limit: number;
    attempted: number;
    tried_alternative: boolean;
    selected_clip_id: string | null;
    stop_reason: string;
    notice: string | null;
  };
  identified_players?: ObservedPlayerProfile[];
  observed_from_player_id?: string;
  observed_object_id?: number;
  identity?: {
    version: number;
    status: "corroborated" | "unconfirmed" | "tracking_rejected";
    expected_name: string;
    expected_team: string;
    expected_jersey: string | null;
    source_ref: string | null;
    source_date: string | null;
    method: string;
    reasons: string[];
    continuity_frames: number[];
    evidence: {
      frame: number;
      time: number;
      jersey_number: string;
      team: string;
      crop_url: string;
      source_url: string;
      evidence: string;
    }[];
    tracked_players: {
      object_id: number;
      role: string;
      name: string | null;
      team: string | null;
      jersey_number: string | null;
      status: string;
    }[];
  };
  footage_sources?: {
    title: string;
    url: string;
    game_date: string;
    publisher: string;
    status: string;
  }[];
  footage_notice?: string | null;
  player: Player;
  clip: Clip | null;
  verified: boolean;
  verification?: { reason: string; confidence: number };
  quality: number;
  tracking_accepted?: boolean;
  metrics: Metric[];
  tracking: Tracking | null;
  overlays: string[];
  critiques: Critique[];
  verdict: Verdict;
};
export type Move = {
  add_player: Player;
  drop_player: Player;
  faab_bid: number | null;
  reasoning: string;
  status: string;
  executed: boolean;
};
export type ScanEvent = {
  id: number;
  created_at: string;
  stage: string;
  actor: string;
  message: string;
  detail: Record<string, unknown>;
};
export type Scan = {
  reviewed?: boolean;
  action_needed?: {
    destination: "data" | "connect";
    section?: "rules" | "statistics";
    label: string;
  } | null;
  id: string;
  stage: string;
  progress: number;
  instruction: string;
  mode: "mock" | "live";
  created_at: string;
  error: string | null;
  attempts: number;
  live_calls: number;
  events?: ScanEvent[];
  result: {
    data_refresh?: {
      roster_updated_at: string | null;
      stats_updated_at: string | null;
      stats_refresh_id: string | null;
    } | null;
    film_test?: boolean;
    candidates: Candidate[];
    staged_move: Move | null;
    card: {
      url: string;
      simulated: boolean;
      player_id: string;
      visual_source: string;
    } | null;
    card_error: string | null;
    guardrail_notice?: string;
    simulated: boolean;
    league_is_demo?: boolean;
    shortlist: { roster_need: string; reasoning: string };
  } | null;
};
