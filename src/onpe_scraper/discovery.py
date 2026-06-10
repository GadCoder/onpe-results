"""Network discovery via a real browser.

This module drives the ONPE SPA with Playwright and records every XHR/fetch the
Angular app fires at the ``/presentacion-backend`` API. Because the edge WAF
fingerprints TLS, the *only* fully reliable way to learn the exact request
signatures (query params, POST bodies, response envelopes) is to watch a genuine
browser make them — which is what this does.

The output is an :class:`ApiManifest`: one entry per endpoint *template* (the
path with numeric/ubigeo segments collapsed), aggregating every distinct
parameter set and a sample response. The replay client in :mod:`onpe_scraper.api`
is built to match what this records, so re-running discovery after the site
changes tells you immediately whether the contract drifted.

Run it via ``python -m onpe_scraper.cli discover`` (headed by default).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .config import Settings

# Path segments that are really identifiers, collapsed so that
# ``proceso/3/elecciones`` and ``proceso/10/elecciones`` fold into one template.
_ID_SEGMENT = re.compile(r"^\d+$|^[0-9]{6}$")


def _template(path: str) -> str:
    parts = [("{id}" if _ID_SEGMENT.match(seg) else seg) for seg in path.split("/")]
    return "/".join(parts)


def _shape(value: Any, depth: int = 0) -> Any:
    """Reduce a JSON value to its structure (keys/types), not its data."""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


@dataclass
class Endpoint:
    """Everything we learned about one endpoint template."""

    template: str
    methods: set[str] = field(default_factory=set)
    param_sets: list[dict[str, list[str]]] = field(default_factory=list)
    post_bodies: list[Any] = field(default_factory=list)
    sample_url: str = ""
    sample_status: int | None = None
    response_shape: Any = None

    def record_params(self, params: dict[str, list[str]]) -> None:
        keyset = {k: v for k, v in params.items()}
        if keyset not in self.param_sets:
            self.param_sets.append(keyset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "methods": sorted(self.methods),
            "param_keys": sorted({k for ps in self.param_sets for k in ps}),
            "param_sets": self.param_sets,
            "post_bodies": self.post_bodies,
            "sample_url": self.sample_url,
            "sample_status": self.sample_status,
            "response_shape": self.response_shape,
        }


class ApiManifest:
    """Collects :class:`Endpoint` records keyed by template."""

    def __init__(self) -> None:
        self._endpoints: dict[str, Endpoint] = {}

    def observe(
        self,
        method: str,
        url: str,
        post_body: Any,
        status: int | None,
        response_json: Any,
    ) -> None:
        split = urlsplit(url)
        template = _template(split.path)
        ep = self._endpoints.setdefault(template, Endpoint(template=template))
        ep.methods.add(method.upper())
        ep.record_params(parse_qs(split.query))
        if post_body not in (None, "") and post_body not in ep.post_bodies:
            ep.post_bodies.append(post_body)
        if ep.response_shape is None and response_json is not None:
            ep.sample_url = url
            ep.sample_status = status
            ep.response_shape = _shape(response_json)

    def to_dict(self) -> dict[str, Any]:
        return {tpl: ep.to_dict() for tpl, ep in sorted(self._endpoints.items())}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._endpoints)


class DiscoveryRecorder:
    """Drives the SPA and produces an :class:`ApiManifest`.

    Parameters
    ----------
    settings:
        Shared configuration (only ``base_url`` / ``api_prefix`` are used here).
    headed:
        Launch a visible browser window (the default, per the discovery goal).
        Set ``False`` for CI.
    interact:
        When ``True`` (default) the recorder clicks through dropdowns and tabs to
        provoke the geo-filtered and per-election requests, not just the initial
        page loads.
    channel:
        Browser channel to launch (default ``"chrome"`` — the real installed
        Chrome). This matters: the edge WAF fingerprints TLS, and Playwright's
        *bundled* headless Chromium is rejected (its ``main.js`` comes back as
        the SPA shell, so Angular never boots and fires no XHR). A real headed
        Chrome passes — which is exactly why discovery must run non-headless.
        Pass ``channel=None`` to use the bundled Chromium.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        headed: bool = True,
        interact: bool = True,
        channel: str | None = "chrome",
    ) -> None:
        self.settings = settings
        self.headed = headed
        self.interact = interact
        self.channel = channel
        self.manifest = ApiManifest()

    def run(self) -> ApiManifest:
        # Imported lazily so the rest of the package works without Playwright.
        from playwright.sync_api import sync_playwright

        launch_kwargs: dict[str, Any] = {"headless": not self.headed}
        if self.channel:
            launch_kwargs["channel"] = self.channel

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**launch_kwargs)
            page = browser.new_page()
            page.on("response", self._on_response)

            self._visit_resumen(page)
            self._visit_actas(page)

            browser.close()
        return self.manifest

    # -- network listener -------------------------------------------------

    def _on_response(self, response: Any) -> None:
        request = response.request
        if self.settings.api_prefix not in request.url:
            return
        body: Any = None
        if request.method.upper() == "POST":
            try:
                body = request.post_data_json
            except Exception:
                body = request.post_data
        payload: Any = None
        try:
            ctype = response.headers.get("content-type", "")
            if "json" in ctype:
                payload = response.json()
        except Exception:
            payload = None
        self.manifest.observe(
            request.method, request.url, body, response.status, payload
        )

    # -- scripted interactions -------------------------------------------

    def _visit_resumen(self, page: Any) -> None:
        page.goto(f"{self.settings.base_url}/main/resumen", wait_until="networkidle")
        if not self.interact:
            return
        # Drill into the geographic selectors to fire ubigeo_nivel_* requests.
        self._exercise_selects(page)

    def _visit_actas(self, page: Any) -> None:
        try:
            page.goto(f"{self.settings.base_url}/main/actas", wait_until="networkidle")
        except Exception:
            return
        if not self.interact:
            return
        self._exercise_selects(page)

    @staticmethod
    def _exercise_selects(page: Any) -> None:
        """Open every Material dropdown and pick its first real option.

        Best-effort: the SPA's exact markup may change, so each step is guarded.
        Each selection triggers a fresh cascade of API calls that the response
        listener captures.
        """
        try:
            page.wait_for_timeout(1500)
            triggers = page.locator("mat-select, select").all()
        except Exception:
            triggers = []
        for trigger in triggers[:6]:
            try:
                trigger.click(timeout=2000)
                page.wait_for_timeout(400)
                option = page.locator("mat-option, option").nth(1)
                option.click(timeout=2000)
                page.wait_for_timeout(1200)
            except Exception:
                # Close any open overlay and move on.
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
