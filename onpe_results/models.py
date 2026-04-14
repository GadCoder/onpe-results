from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RouteConfig:
    key: str
    page_url: str
    election_id: int
    mode: str
    participants_path: str


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    raw_payload: dict[str, Any]


@dataclass
class ApiResult:
    request_url: str
    status_code: int | None
    payload: Any | None
    error: str | None

    @property
    def ok(self) -> bool:
        if self.error is not None:
            return False
        if self.status_code is None:
            return False
        if self.status_code < 200 or self.status_code >= 300:
            return False
        if isinstance(self.payload, dict) and self.payload.get("success") is False:
            return False
        return True
