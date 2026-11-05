import base64

from backend.config import settings
from backend.models.base import ModelError
from backend.models.transport import MetaTransport


class MuseImage:
    def __init__(self, job, transport=None):
        self.job, self.transport = job, transport or MetaTransport()

    def generate(self, prompt):
        response = self.job.cached(
            settings.image_model,
            "image",
            {"prompt": prompt, "format": "png"},
            lambda: self.transport.post(
                "/images/generations",
                {
                    "model": settings.image_model,
                    "prompt": prompt,
                    "n": 1,
                    "response_format": "b64_json",
                    "output_format": "png",
                },
            ),
        )
        try:
            return base64.b64decode(response["data"][0]["b64_json"], validate=True)
        except (KeyError, IndexError, ValueError, TypeError):
            raise ModelError(
                "Muse Image returned no valid image bytes. Card generation unavailable."
            ) from None
