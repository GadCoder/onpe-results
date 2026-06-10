"""Central configuration for the ONPE results scraper.

All tunables live here so the HTTP client, API layer and orchestrator share a
single source of truth. Nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Public host serving the 2026 second-round presidential results.
BASE_URL = "https://resultadosegundavuelta.onpe.gob.pe"

#: All JSON endpoints live under this path prefix behind the SPA.
API_PREFIX = "/presentacion-backend"

#: The page the SPA itself uses as ``Referer`` for its XHR calls. The edge WAF
#: is lenient about this, but sending it keeps requests indistinguishable from
#: the real frontend.
DEFAULT_REFERER = f"{BASE_URL}/main/resumen"

#: curl_cffi browser-impersonation profile. The edge rejects clients whose TLS
#: fingerprint does not match a real browser (you get the Angular shell instead
#: of JSON), so this is mandatory, not cosmetic.
DEFAULT_IMPERSONATE = "chrome124"

#: Default SOCKS proxy used when ``--proxy`` is given without a value. The site
#: filters datacenter IPs, so from a VPS requests must exit through a residential
#: IP — here a Tailscale + Android SOCKS5 exit. ``socks5h`` resolves DNS through
#: the proxy too (matches ``curl --socks5-hostname``).
DEFAULT_PROXY = "socks5h://100.66.12.22:1080"


@dataclass(slots=True)
class Settings:
    """Runtime knobs for a scrape/discovery run."""

    base_url: str = BASE_URL
    api_prefix: str = API_PREFIX
    referer: str = DEFAULT_REFERER
    impersonate: str = DEFAULT_IMPERSONATE

    # Politeness / resilience.
    requests_per_second: float = 6.0
    """Soft client-side rate limit. The site is a public good during an
    election; stay well below anything that looks like an attack."""

    max_retries: int = 4
    backoff_base: float = 0.75
    backoff_max: float = 20.0
    timeout: float = 30.0

    #: SOCKS/HTTP proxy URL (e.g. ``socks5h://host:port``) or None for direct.
    proxy: str | None = None

    # Output.
    output_dir: Path = field(default_factory=lambda: Path("data"))

    @property
    def api_base(self) -> str:
        return f"{self.base_url}{self.api_prefix}"


#: Time zone results are reported in (Peru has no DST).
REPORT_TZ = "America/Lima"

#: Display name + colour emoji per political organisation (``codigoAgrupacionPolitica``).
#: The API only gives long legal names ("KEIKO SOFIA FUJIMORI HIGUCHI"); this maps
#: them to the short forms and party colours used in notifications. Unknown codes
#: fall back to a title-cased API name and a neutral marker.
CANDIDATE_DISPLAY: dict[int, dict[str, str]] = {
    8: {"nombre": "Keiko Fujimori", "emoji": "🟥"},   # Fuerza Popular
    10: {"nombre": "Roberto Sánchez", "emoji": "🟦"},  # Juntos por el Perú
}
FALLBACK_EMOJI = "⬜"
