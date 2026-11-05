from backend.api.types import Decision
from backend.services.staging import validate_decision


class DecisionAgent:
    def __init__(self, spark):
        self.spark = spark
        self.validation_warnings = []

    def decide(self, instruction, league, candidates, guardrails):
        self.validation_warnings = []
        decision = self.spark.reason(
            "decide",
            {
                "instruction": instruction,
                "roster": league["roster"],
                "scoring": league["scoring"],
                "candidates": [
                    {
                        k: c[k]
                        for k in (
                            "player",
                            "verified",
                            "quality",
                            "metrics",
                            "identity",
                            "identified_players",
                            "observed_from_player_id",
                            "observed_object_id",
                            "footage_notice",
                        )
                        if k in c
                    }
                    | {"tracking_review": (c.get("critiques") or [None])[-1]}
                    for c in candidates
                ],
                "allowed_metric_refs": {
                    c["player"]["id"]: [
                        m["name"]
                        for m in c["metrics"]
                        if m["value"] is not None and m["evidence_frames"]
                    ]
                    for c in candidates
                },
                "guardrails": guardrails.model_dump(),
                "faab_remaining": league["faab_remaining"],
                "game_mode": league.get("rules", {}).get("game_mode", "sample"),
                "waiver_mode": league.get("rules", {}).get("waiver_mode", "sample"),
                "statistics_source": league.get("stats_summary"),
                "eligibility": league.get("scan_readiness"),
                "observed_players": "Identified-player profiles join dated roster IDs to statistics. Candidates observed_from_player_id reuse independently checked tracks from the same clip; evaluate each candidate using only their own metrics and recent games. Other observed profiles are context, not additional add candidates. A highlight is a selected short sample, not a measure of whole-game efficiency or usage. Write rationales in plain language without internal field names. An available player may still require waiver/lock review.",
                "valuation": "Use recent_fantasy_average and recent source rows for comparisons. fantasy_points is a reported period total in a real Sleeper league. No games-per-week multiplication in Lock-In/Game Pick. Return null faab_bid for non-FAAB moves. Eligibility and lock evidence may be unknown; never guarantee a legal transaction.",
                "rules": "Use only allowed_metric_refs for that player. Set metric_refs to [] when no measured metric supports the verdict; never cite an unavailable measurement. No ADD without verified reliable film; acknowledge sample size and proxies. For real athletes, no ADD or move unless the candidate has eligible_drop_ids; choose a drop only from that list. Otherwise return MONITOR or PASS with no move and explain the missing eligibility evidence. Never drop protected players.",
            },
            Decision,
        )
        # A model's unsupported interpretation is withheld, not repaired into
        # evidence. Keep the raw cached response for audit and apply the same
        # strict validator to this conservative report-only result.
        by_id = {c["player"]["id"]: c for c in candidates}
        for verdict in decision.verdicts:
            candidate = by_id.get(verdict.player_id)
            if not candidate:
                continue
            measured = {
                m["name"]
                for m in candidate["metrics"]
                if m["value"] is not None and m["evidence_frames"]
            }
            unsupported = sorted(set(verdict.metric_refs) - measured)
            if unsupported:
                self.validation_warnings.append(
                    {
                        "player_id": verdict.player_id,
                        "unsupported_metric_refs": unsupported,
                        "action": "interpretation_withheld",
                    }
                )
                verdict.verdict = "MONITOR"
                verdict.confidence = 0
                verdict.metric_refs = []
                verdict.rationale = "The model returned references that did not match the verified film measurements, so its interpretation was withheld. Review the available evidence; no add/drop is recommended."
                verdict.strengths = []
                verdict.weaknesses = [
                    "Unsupported model interpretation withheld; more reliable film evidence is needed."
                ]
        if self.validation_warnings:
            decision.move = None
        return validate_decision(
            decision,
            candidates,
            league["roster"],
            guardrails,
            league["faab_remaining"],
            league=league,
        )
