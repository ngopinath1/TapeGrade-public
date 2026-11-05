import math
from decimal import Decimal
from typing import Protocol


class LeagueProvider(Protocol):
    def snapshot(self) -> dict: ...


class ScoringEngine:
    """Exact per-game scoring; unsupported rules and missing fields fail closed."""

    aliases = {"turnover": "to", "tov": "to", "fg3m": "tpm", "fg3a": "tpa"}
    base_fields = {
        "pts",
        "reb",
        "ast",
        "stl",
        "blk",
        "to",
        "tpm",
        "tpa",
        "fgm",
        "fga",
        "ftm",
        "fta",
        "oreb",
        "dreb",
        "pf",
        "tf",
        "ff",
    }

    def evaluate(self, stats: dict, weights: dict, rules: dict | None = None) -> dict:
        values = {self.aliases.get(k, k): v for k, v in stats.items()}
        values = {
            k: v
            for k, v in values.items()
            if isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            and v >= 0
        }
        values = {k: v for k, v in values.items() if k in self.base_fields}
        categories = ("pts", "reb", "ast", "stl", "blk")
        if all(k in values for k in categories):
            doubles = sum(values[k] >= 10 for k in categories)
            values.update(dd=int(doubles >= 2), td=int(doubles >= 3))
        for key, made, attempts in [
            ("fgmi", "fgm", "fga"),
            ("ftmi", "ftm", "fta"),
            ("tpmi", "tpm", "tpa"),
        ]:
            if made in values and attempts in values and values[attempts] >= values[made]:
                values[key] = values[attempts] - values[made]
        rules = rules or {}
        enabled = {k: w for k, w in weights.items() if w != 0}
        reasons = []
        for k, w in enabled.items():
            if not isinstance(w, (int, float)) or isinstance(w, bool) or not math.isfinite(w):
                reasons.append("Invalid scoring weight: " + k)
        bonuses = {"bonus_pt_40p": 40, "bonus_pt_50p": 50}
        if set(enabled) & bonuses.keys():
            mode = rules.get("point_bonus_mode", "unknown")
            if mode not in ("stack", "highest_only"):
                reasons.append("40/50-point bonus stacking has not been verified.")
            elif "pts" in values:
                for key, threshold in bonuses.items():
                    values[key] = int(values["pts"] >= threshold)
                if mode == "highest_only" and values["pts"] >= 50:
                    values["bonus_pt_40p"] = 0
        missing = sorted(set(enabled) - values.keys())
        reasons += ["Missing or unsupported scoring field: " + key for key in missing]
        return {
            "score": (
                None
                if reasons
                else float(
                    sum(Decimal(str(values[k])) * Decimal(str(w)) for k, w in enabled.items())
                )
            ),
            "missing_fields": missing,
            "reasons": reasons,
            "events": {k: values[k] for k in enabled if k in values},
        }

    def score(self, stats: dict, weights: dict, rules: dict | None = None) -> float | None:
        return self.evaluate(stats, weights, rules)["score"]
