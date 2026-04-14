"""Backward-compatible public API.

The implementation was split into the `onpe_results` package.
"""

from onpe_results.cli import main, run_scraper
from onpe_results.models import ApiResult, Region, RouteConfig
from onpe_results.routes import ROUTES

__all__ = [
    "ApiResult",
    "Region",
    "RouteConfig",
    "ROUTES",
    "run_scraper",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
