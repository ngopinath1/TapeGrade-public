"""Explicit credential/catalog check; --spark authorizes ONE capped inference call.

No video/image inference, retries, environment edits, or background scheduling.
Run: .venv/bin/python -m scripts.live_check [--spark]
"""

import argparse
from datetime import datetime, timezone
import json
import re

import httpx

from backend.agents.scout import ScoutAgent
from backend.config import settings
from backend.models.base import ModelError
from backend.models.muse_spark import MuseSpark
from backend.models.transport import MetaTransport


class OneCallTransport:
    def __init__(self, transport):
        self.transport = transport
        self.calls = 0
        self.usage = {}

    def post(self, path, payload):
        if self.calls:
            raise ModelError("Live check permits only one inference attempt.")
        self.calls += 1
        result = self.transport.post(path, payload)
        usage = result.get("usage", {})
        self.usage = {
            key: value
            for key, value in usage.items()
            if key in ("prompt_tokens", "completion_tokens", "total_tokens")
            and isinstance(value, int)
        }
        return result


def check(spark=False, client=None):
    key = settings.model_api_key.get_secret_value()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "credential_present": bool(key),
        "inference_calls_attempted": 0,
        "catalog_requests_attempted": 0,
        "spark_inference": "not_requested",
        "sam_inference": "not_run",
        "image_inference": "not_run",
    }
    if not key or key != key.strip() or re.search(r"\s", key):
        report["error"] = (
            "MODEL_API_KEY is missing or contains whitespace. Key value was not displayed."
        )
        return report
    if settings.meta_base_url.rstrip("/") != "https://api.meta.ai":
        report["error"] = (
            "Credential check only sends credentials to the official https://api.meta.ai origin."
        )
        return report
    owned_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False)
    original_mode = settings.mock_models
    probe = None
    try:
        report["catalog_requests_attempted"] = 1
        response = client.get(
            "https://api.meta.ai/v1/models", headers={"Authorization": f"Bearer {key}"}
        )
        report["catalog_http_status"] = response.status_code
        if response.status_code != 200:
            MetaTransport.check(response)
            raise ModelError("Meta returned an unexpected redirect; no inference attempted.")
        data = response.json()
        if not isinstance(data.get("data"), list):
            raise ModelError("Meta model catalog has an unexpected response shape.")
        ids = {
            m["id"] for m in data["data"] if isinstance(m, dict) and isinstance(m.get("id"), str)
        }
        expected = [settings.spark_model, settings.sam_model, settings.image_model]
        report["authentication_accepted"] = True
        report["model_access"] = {model: model in ids for model in expected}
        if not spark:
            return report
        if settings.spark_model not in ids:
            raise ModelError("Configured Muse Spark model is unavailable; no inference attempted.")
        # --spark opts in for this process only. Never edit the user's .env.
        settings.mock_models = False
        probe = OneCallTransport(MetaTransport(client))
        model = MuseSpark(probe, max_completion_tokens=512, reasoning_effort="minimal")
        league = {
            "available": [
                {
                    "id": "c1",
                    "name": "Cameron Reed",
                    "positions": ["PG"],
                    "minutes": 29,
                    "previous_minutes": 21,
                    "fantasy_points": 29.9,
                    "source": "Fictional demo data; connectivity check only",
                }
            ],
            "roster": [],
            "scoring": {"type": "points"},
        }
        result = ScoutAgent(model).shortlist(
            "Integration check with fictional data: shortlist the only available guard. Use one short sentence for reasoning.",
            league,
            1,
        )
        report.update(
            spark_inference="passed",
            structured_output_valid=True,
            selected_player_ids=result.player_ids,
            usage=probe.usage,
            output_token_limit=512,
            reasoning_effort="minimal",
        )
    except ModelError as error:
        report["error"] = str(error)
        if spark and probe:
            report["spark_inference"] = "failed"
    except httpx.HTTPError as error:
        report["error"] = (
            f"Meta network request failed ({type(error).__name__}); no automatic retry."
        )
    except (ValueError, KeyError, TypeError):
        report["error"] = (
            "Meta response failed validation. Raw responses and credentials were not displayed."
        )
    finally:
        if probe:
            report["inference_calls_attempted"] = probe.calls
        settings.mock_models = original_mode
        if owned_client:
            client.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spark",
        action="store_true",
        help="Opt in to one paid Spark request, capped at 512 output tokens.",
    )
    args = parser.parse_args()
    report = check(args.spark)
    path = settings.data_dir / "cache" / "live-check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(1 if report.get("error") else 0)


if __name__ == "__main__":
    main()
