from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from app.domain.body_value_validation import finite_number


@dataclass(frozen=True, slots=True)
class HttpBodyPoseOutputConfig:
    """BodyPoseFrame受信先へ接続する暫定HTTP Transport設定。"""

    base_url: str
    timeout_seconds: float = 1.0
    endpoint_path: str = "/api/body-pose-frame"
    source_name: str = "yura-core-state-driven-body"

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str):
            raise TypeError("base_url must be a string")
        base_url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http or https URL")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain query or fragment")

        timeout = finite_number(self.timeout_seconds, "timeout_seconds")
        if not 0.05 <= timeout <= 30.0:
            raise ValueError("timeout_seconds must be between 0.05 and 30")

        if not isinstance(self.endpoint_path, str):
            raise TypeError("endpoint_path must be a string")
        endpoint = self.endpoint_path.strip()
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("endpoint_path must start with one slash")
        if "?" in endpoint or "#" in endpoint:
            raise ValueError("endpoint_path must not contain query or fragment")

        if not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string")
        source_name = self.source_name.strip()
        if not source_name or len(source_name) > 80:
            raise ValueError("source_name must contain 1 to 80 characters")

        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "endpoint_path", endpoint)
        object.__setattr__(self, "source_name", source_name)

    @property
    def endpoint_url(self) -> str:
        return f"{self.base_url}{self.endpoint_path}"
