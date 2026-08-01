"""Version and compatibility rules for the Streaming public contract."""

from dataclasses import dataclass

UNKNOWN_FIELD_POLICY = "ignore"
UNKNOWN_EVENT_TYPE_POLICY = "ignore"
UNKNOWN_ENUM_POLICY = "safe_fallback"


@dataclass(frozen=True, slots=True)
class StreamingApiVersion:
    """Major/minor version of the public Streaming schema."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 1:
            raise ValueError("major version must be at least 1")
        if self.minor < 0:
            raise ValueError("minor version must not be negative")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


CURRENT_STREAMING_API_VERSION = StreamingApiVersion(major=1, minor=0)


def is_streaming_api_compatible(
    consumer: StreamingApiVersion,
    producer: StreamingApiVersion,
) -> bool:
    """Return whether additive minor-version evolution is compatible."""

    return consumer.major == producer.major
