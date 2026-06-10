"""Low-level HTTP client for the ONPE backend.

Wraps a ``curl_cffi`` session that impersonates a real Chrome TLS fingerprint --
without this the edge WAF returns the Angular SPA shell (``text/html``) instead
of JSON. On top of that it adds:

* a token-bucket rate limiter (be a good citizen against a public election site),
* retry with exponential backoff on transient failures (via ``tenacity``),
* unwrapping of the ``{"success", "message", "data"}`` envelope, and
* detection of the "SPA shell instead of JSON" failure mode, surfaced as a
  clear :class:`BlockedError` rather than a confusing parse error.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from curl_cffi import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings

logger = logging.getLogger(__name__)


class OnpeError(RuntimeError):
    """Base class for client errors."""


class BlockedError(OnpeError):
    """The edge served the SPA shell instead of JSON (TLS fingerprint rejected,
    or the route does not exist and fell through to ``index.html``)."""


class ApiError(OnpeError):
    """The API returned a JSON error envelope or a non-2xx status."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _RateLimiter:
    """Minimal thread-safe token bucket sized by ``requests_per_second``."""

    def __init__(self, rate: float) -> None:
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


class OnpeClient:
    """Issues GET/POST requests and returns the unwrapped ``data`` payload."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._session = requests.Session(impersonate=self.settings.impersonate)
        self._limiter = _RateLimiter(self.settings.requests_per_second)
        self._headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
            "Referer": self.settings.referer,
            "Content-Type": "application/json",
        }

    # -- public API -------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, body=body)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> OnpeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.settings.api_base}/{path.lstrip('/')}"
        clean_params = _drop_none(params) if params else None

        @retry(
            retry=retry_if_exception_type((BlockedError, requests.errors.RequestsError)),
            stop=stop_after_attempt(self.settings.max_retries),
            wait=wait_exponential(
                multiplier=self.settings.backoff_base, max=self.settings.backoff_max
            ),
            reraise=True,
        )
        def _do() -> Any:
            self._limiter.wait()
            logger.debug("%s %s params=%s body=%s", method, url, clean_params, body)
            resp = self._session.request(
                method,
                url,
                params=clean_params,
                data=json.dumps(body) if body is not None else None,
                headers=self._headers,
                timeout=self.settings.timeout,
            )
            return self._parse(resp, method, url)

        return _do()

    def _parse(self, resp: Any, method: str, url: str) -> Any:
        # 204 / empty body is a legitimate "no data for this scope" answer (e.g.
        # a foreign UBIGEO queried under the Peru ambito) — NOT a block. Returning
        # None here is what keeps the crawler fast: misclassifying it as a block
        # would trigger pointless retries with backoff.
        if resp.status_code == 204 or not resp.content:
            return None

        ctype = resp.headers.get("content-type", "")
        if "application/json" not in ctype:
            # A non-empty, non-JSON body is the Angular shell: CloudFront maps
            # WAF blocks / unknown routes to index.html (200).
            raise BlockedError(
                f"{method} {url} returned {resp.status_code} {ctype!r} "
                f"(SPA shell, not JSON) — TLS fingerprint rejected or route absent"
            )

        try:
            envelope = resp.json()
        except Exception as exc:  # pragma: no cover - defensive
            raise ApiError(f"invalid JSON from {url}: {exc}", resp.status_code) from exc

        if resp.status_code >= 400 or (
            isinstance(envelope, dict) and envelope.get("status", 0) >= 400
        ):
            msg = (
                envelope.get("message") or envelope.get("error")
                if isinstance(envelope, dict)
                else str(envelope)
            )
            raise ApiError(f"{method} {url}: {msg}", resp.status_code)

        # Standard envelope is {success, message, data}; some endpoints return
        # the payload bare.
        if isinstance(envelope, dict) and "data" in envelope:
            if envelope.get("success") is False:
                raise ApiError(
                    f"{method} {url}: {envelope.get('message')}", resp.status_code
                )
            return envelope["data"]
        return envelope


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Keep empty strings (the geo endpoints expect them) but drop ``None``."""
    return {k: v for k, v in d.items() if v is not None}
