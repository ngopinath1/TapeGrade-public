from typing import Protocol, TypeVar

from pydantic import BaseModel

from backend.api.types import Tracking

T = TypeVar("T", bound=BaseModel)


class SparkClient(Protocol):
    def reason(
        self, operation: str, payload: dict, schema: type[T], images: list[str] | None = None
    ) -> T: ...


class SegmentationClient(Protocol):
    def track(self, clip: dict, prompt: str, objects: list[dict]) -> Tracking: ...


class ImageClient(Protocol):
    def generate(self, prompt: str) -> bytes: ...


class ModelError(RuntimeError):
    """Safe to display: never include a request, authorization header, or raw error body."""
