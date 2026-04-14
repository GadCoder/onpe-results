from __future__ import annotations

import time
from typing import Any

import requests

from .models import ApiResult
from .routes import API_BASE, BASE_URL, DEFAULT_USER_AGENT


class OnpeApiClient:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
                "Origin": BASE_URL,
                "Connection": "keep-alive",
            }
        )

    def get_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        referer: str,
    ) -> ApiResult:
        url = f"{API_BASE}{path}"
        request_params = dict(params)
        # Attach a cache-busting request timestamp to every outbound HTTP call.
        request_params.setdefault("timestamp", int(time.time() * 1000))

        try:
            response = self.session.get(
                url,
                params=request_params,
                headers={"Referer": referer},
                timeout=self.timeout_seconds,
            )
            request_url = response.url
            status_code = response.status_code

            try:
                payload = response.json()
            except ValueError:
                payload = {"raw_text": response.text}

            if status_code < 200 or status_code >= 300:
                return ApiResult(
                    request_url=request_url,
                    status_code=status_code,
                    payload=payload,
                    error=f"HTTP {status_code}",
                )

            return ApiResult(
                request_url=request_url,
                status_code=status_code,
                payload=payload,
                error=None,
            )
        except requests.RequestException as exc:
            return ApiResult(
                request_url=url,
                status_code=None,
                payload=None,
                error=str(exc),
            )
