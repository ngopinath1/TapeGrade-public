import base64
import json

import httpx

from backend.config import settings
from backend.models.base import ModelError
from backend.services.clips import local_path


def data_url(url: str, mime="image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(local_path(url).read_bytes()).decode()


class MetaTransport:
    """One paid request per call. No blind retries on ambiguous inference timeouts."""

    def __init__(self, client=None):
        key = settings.model_api_key.get_secret_value()
        if not key:
            raise ModelError("MODEL_API_KEY is missing. Configure the backend environment.")
        if settings.mock_models:
            raise ModelError("Real model clients are disabled while MOCK_MODELS=1.")
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.model_timeout_seconds, connect=15)
        )
        self.headers = {"Authorization": f"Bearer {key}"}
        self.base = settings.meta_base_url.rstrip("/") + "/v1"

    def post(self, path, payload):
        try:
            response = self.client.post(self.base + path, headers=self.headers, json=payload)
            self.check(response)
            return response.json()
        except httpx.TimeoutException:
            raise ModelError(
                "Meta request timed out. No automatic paid retry was made; the request may have been billed."
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "Cannot reach Meta Model API. Check your network and service availability."
            ) from None
        except (ValueError, KeyError):
            raise ModelError(
                "Meta returned an invalid response. No mock result was substituted."
            ) from None

    @staticmethod
    def check(response):
        code = response.status_code
        if code >= 400:
            description = {
                400: "Request rejected; check supported model inputs.",
                401: "API key rejected.",
                403: "Model access denied.",
                404: "Requested model or endpoint is unavailable.",
                429: "Rate limit reached. Wait before manually retrying.",
                500: "Service error.",
                503: "Model temporarily unavailable.",
            }.get(code, "Request failed.")
            raise ModelError(f"Meta API {code}: {description}")

    def stream_text(self, payload):
        chunks = []
        completed = False
        try:
            with self.client.stream(
                "POST",
                self.base + "/responses",
                headers={**self.headers, "Accept": "text/event-stream"},
                json=payload,
            ) as response:
                self.check(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    event = json.loads(body)
                    if event.get("type") == "response.output_text.delta":
                        chunks.append(event.get("delta", ""))
                    elif event.get("type") == "response.completed":
                        completed = True
                    elif event.get("type") in ("error", "response.failed", "response.incomplete"):
                        raise ModelError(
                            "SAM response failed or was incomplete. Partial tracks were not accepted."
                        )
            if not completed:
                raise ModelError(
                    "SAM stream ended without response.completed. Partial results were not accepted."
                )
            return "".join(chunks)
        except httpx.TimeoutException:
            raise ModelError(
                "SAM request timed out. It may have been billed; retry manually when ready."
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "SAM network request failed. No simulated fallback was used."
            ) from None
        except json.JSONDecodeError:
            raise ModelError("SAM returned malformed streaming data.") from None
