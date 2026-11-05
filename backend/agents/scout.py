from backend.api.types import Shortlist
from backend.services.player_identity import normalized_name
import re


def explicit_inspection(instruction, league):
    """Honor a named inspection without asking an LLM whether to inspect it.

    Selection is not an ADD verdict. Duplicate names and negative requests are
    deliberately left to normal scouting rather than bound to an arbitrary ID.
    """
    match = re.match(
        r"^(?:please\s+)?(?:review|inspect|analy[sz]e|evaluate|scout|check)\s+(.+)$",
        instruction.strip(),
        re.I,
    )
    if not match:
        return None
    target = normalized_name(match.group(1))
    matches = [
        p
        for p in league["available"]
        if re.match(re.escape(normalized_name(p["name"])) + r"(?: |$)", target)
    ]
    if len(matches) != 1:
        return None
    player = matches[0]
    return Shortlist(
        player_ids=[player["id"]],
        roster_need="Inspect the explicitly requested player",
        reasoning=f"{player['name']} was selected by name for film inspection. This selection is not an add recommendation; evidence and roster checks determine the final verdict.",
    )


class ScoutAgent:
    def __init__(self, spark):
        self.spark = spark

    def shortlist(self, instruction: str, league: dict, limit: int) -> Shortlist:
        requested = explicit_inspection(instruction, league)
        if requested:
            return requested
        result = self.spark.reason(
            "scout",
            {
                "instruction": instruction,
                "available": league["available"],
                "roster": league["roster"],
                "scoring": league["scoring"],
                "game_mode": league.get("rules", {}).get("game_mode", "sample"),
                "valuation": "Compare exact recent per-game averages with sample sizes. Lock-In and Game Pick count one game per player per week; never multiply a mean by games scheduled. Unrostered does not establish eligibility.",
                "limit": limit,
                "film_context": "Prefer a useful candidate with available permitted footage when choosing among comparable fits. has_usable_film indicates availability only, not verified identity or tracking quality.",
                "selection_task": "Select players worth inspecting, not only players already proven to be strong ADDs. Missing film verification and unknown transaction eligibility are checked later; they do not by themselves justify an empty inspection shortlist. Final ADD/MONITOR/PASS verdicts belong to the decision stage.",
            },
            Shortlist,
        )
        available = {p["id"] for p in league["available"]}
        if (
            len(result.player_ids) > limit
            or len(set(result.player_ids)) != len(result.player_ids)
            or not set(result.player_ids) <= available
        ):
            raise ValueError("Scout returned an invalid shortlist.")
        return result
