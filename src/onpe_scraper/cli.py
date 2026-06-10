"""Command-line interface.

Subcommands::

    onpe-scraper scrape    # crawl all results to JSON + CSV
    onpe-scraper discover  # record the SPA's API calls with a real browser
    onpe-scraper mesa CODE # look up a single polling-station acta

Run ``python -m onpe_scraper.cli <command> -h`` for options.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .api import OnpeApi
from .config import DEFAULT_PROXY, Settings
from .http import OnpeClient, OnpeError
from .scraper import GeoLevel, OnpeScraper
from .storage import Storage


def _build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings()
    if getattr(args, "rps", None):
        settings.requests_per_second = args.rps
    if getattr(args, "output", None):
        settings.output_dir = Path(args.output)
    if getattr(args, "proxy", None):
        settings.proxy = args.proxy
    return settings


def _add_proxy_flag(p: argparse.ArgumentParser) -> None:
    """``--proxy`` (bare → the hardcoded default) routes traffic via a SOCKS
    proxy, needed when the host IP is filtered by the edge (e.g. a VPS)."""
    p.add_argument(
        "--proxy",
        nargs="?",
        const=DEFAULT_PROXY,
        default=None,
        metavar="URL",
        help=f"route via SOCKS/HTTP proxy; bare --proxy uses {DEFAULT_PROXY}",
    )


def cmd_scrape(args: argparse.Namespace) -> int:
    settings = _build_settings(args)
    storage = Storage(settings.output_dir)

    with OnpeClient(settings) as client:
        api = OnpeApi(client)
        scraper = OnpeScraper(api, progress=lambda m: print(f"  · {m}", flush=True))
        result = scraper.scrape(
            geo_level=GeoLevel.parse(args.geo_level),
            include_abroad=not args.no_abroad,
            id_eleccion=args.id_eleccion,
        )

    storage.write_json("process.json", result.proceso, raw=True)
    storage.write_json("elecciones.json", result.elecciones, raw=True)
    storage.write_json("ubigeos.json", result.ubigeos, raw=True)
    written = storage.write_scopes(result.scopes)

    print(f"\nScraped {len(result.scopes)} scopes into {settings.output_dir}/")
    for label, path in written.items():
        if path:
            print(f"  {label}: {path}")
    if result.errors:
        print(f"  ({len(result.errors)} scopes failed — see scopes.json / logs)")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from .discovery import DiscoveryRecorder

    settings = _build_settings(args)
    recorder = DiscoveryRecorder(
        settings,
        headed=not args.headless,
        interact=not args.no_interact,
        channel=None if args.bundled_chromium else "chrome",
    )
    manifest = recorder.run()
    out = Path(args.manifest)
    manifest.save(out)
    print(f"Captured {len(manifest)} endpoint templates -> {out}")
    if len(manifest) == 0:
        print(
            "  No API calls captured. The WAF blocks headless/bundled Chromium "
            "(Angular never boots). Re-run headed with real Chrome (the default).",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_mesa(args: argparse.Namespace) -> int:
    settings = _build_settings(args)
    with OnpeClient(settings) as client:
        data = OnpeApi(client).buscar_mesa(args.codigo)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import History, build_report, fetch_snapshot

    settings = _build_settings(args)
    history = History(Path(args.history))

    with OnpeClient(settings) as client:
        api = OnpeApi(client)
        eleccion_id = args.id_eleccion or api.proceso_activo().id_eleccion_principal
        current = fetch_snapshot(
            api,
            eleccion_id,
            with_geo=not args.no_geo,
            progress=(lambda m: print(f"  · {m}", flush=True)) if args.verbose else None,
        )

    previous = history.previous_to(current.timestamp)
    report = build_report(current, previous, top_geo=args.top_geo)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Three standalone message files (general / departamentos / países).
    msg_dir = out.parent
    msg_paths = {
        "general": msg_dir / "mensaje_general.txt",
        "departamentos": msg_dir / "mensaje_departamentos.txt",
        "paises": msg_dir / "mensaje_paises.txt",
    }
    for key, path in msg_paths.items():
        path.write_text(report["mensajes"][key], encoding="utf-8")

    is_new = history.append(current)
    print(report["mensajes"]["general"])
    print(f"\n→ report: {out}")
    for key, path in msg_paths.items():
        print(f"→ {key}: {path}")
    print(
        f"→ history: {history.path}"
        + ("" if is_new else " (no new data; unchanged)")
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onpe-scraper", description=__doc__)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable debug logging"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scrape", help="crawl all results to JSON + CSV")
    sp.add_argument(
        "--geo-level",
        default="district",
        choices=["national", "department", "province", "district"],
        help="how deep to sweep totals (default: district = everything)",
    )
    sp.add_argument("--no-abroad", action="store_true", help="skip abroad ambito")
    sp.add_argument("--id-eleccion", type=int, help="override the election id")
    sp.add_argument("--output", default="data", help="output directory (default: data)")
    sp.add_argument("--rps", type=float, help="max requests/second (default: 6)")
    _add_proxy_flag(sp)
    sp.set_defaults(func=cmd_scrape)

    dp = sub.add_parser("discover", help="record the SPA's API calls with a browser")
    dp.add_argument("--manifest", default="data/manifest.json", help="output path")
    dp.add_argument("--headless", action="store_true", help="(usually blocked by WAF)")
    dp.add_argument("--no-interact", action="store_true", help="only record page loads")
    dp.add_argument(
        "--bundled-chromium",
        action="store_true",
        help="use Playwright's Chromium instead of system Chrome",
    )
    _add_proxy_flag(dp)
    dp.set_defaults(func=cmd_discover)

    mp = sub.add_parser("mesa", help="look up a single polling-station acta")
    mp.add_argument("codigo", help="codigoMesa (6-digit)")
    mp.add_argument("--rps", type=float)
    _add_proxy_flag(mp)
    mp.set_defaults(func=cmd_mesa)

    rp = sub.add_parser(
        "report",
        help="national snapshot + delta vs previous; emits notification JSON",
    )
    rp.add_argument("--output", default="data/report.json", help="report JSON path")
    rp.add_argument(
        "--history",
        default="data/history.jsonl",
        help="snapshot history file (for the comparison)",
    )
    rp.add_argument(
        "--no-geo",
        action="store_true",
        help="national race only; skip the per-department/province/country actas sweep",
    )
    rp.add_argument(
        "--top-geo",
        type=int,
        default=10,
        help="max geo rows per group in the message (JSON keeps all; default 10)",
    )
    rp.add_argument("--id-eleccion", type=int, help="override the election id")
    rp.add_argument("--rps", type=float)
    _add_proxy_flag(rp)
    rp.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except OnpeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
