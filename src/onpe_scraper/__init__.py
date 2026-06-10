"""Scraper for ONPE (Peru) live election results.

Public API:
    Settings        -- runtime configuration
    OnpeClient      -- low-level Chrome-impersonated HTTP client
    OnpeApi         -- typed endpoint methods
    OnpeScraper     -- full-crawl orchestrator
    DiscoveryRecorder -- Playwright network recorder
"""

from __future__ import annotations

from .api import OnpeApi
from .config import BASE_URL, Settings
from .http import ApiError, BlockedError, OnpeClient, OnpeError
from .scraper import GeoLevel, OnpeScraper, ScrapeResult

__all__ = [
    "BASE_URL",
    "Settings",
    "OnpeClient",
    "OnpeApi",
    "OnpeScraper",
    "ScrapeResult",
    "GeoLevel",
    "OnpeError",
    "ApiError",
    "BlockedError",
    "__version__",
]
__version__ = "0.1.0"
