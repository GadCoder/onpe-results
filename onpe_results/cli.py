from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import OnpeApiClient
from .database import ScraperDB
from .insights import InsightsService, print_rows
from .routes import ROUTES
from .scraper import OnpeRegionalScraper


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["scrape"]
    if argv[0] in {"scrape", "insights"}:
        return argv
    return ["scrape", *argv]


def parse_args(argv: list[str]) -> argparse.Namespace:
    argv = _normalize_argv(argv)

    parser = argparse.ArgumentParser(
        description="ONPE scraper and insights CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser(
        "scrape",
        help="Run scraper and persist responses to SQLite.",
    )
    scrape_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    scrape_parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Optional sleep between requests in seconds.",
    )
    scrape_parser.add_argument(
        "--routes",
        nargs="*",
        default=None,
        help=(
            "Optional subset of route keys. "
            "Available: " + ", ".join(route.key for route in ROUTES)
        ),
    )

    insights_parser = subparsers.add_parser(
        "insights",
        help="Query normalized insights from an existing DB.",
    )
    insights_subparsers = insights_parser.add_subparsers(dest="insight_command", required=True)

    def add_output_format_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--format",
            dest="output_format",
            choices=["table", "json"],
            default="table",
            help="Output format (default: table).",
        )

    latest_parser = insights_subparsers.add_parser(
        "latest-results",
        help="Show latest results from normalized candidate table.",
    )
    latest_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    latest_parser.add_argument("--route", default=None, help="Route key filter.")
    latest_parser.add_argument("--region", default=None, help="Region name filter.")
    latest_parser.add_argument(
        "--kind",
        default="candidate",
        choices=["candidate", "party_list", "blank_vote", "null_vote", "all"],
        help="Result kind filter.",
    )
    latest_parser.add_argument("--candidate-document", default=None, help="Candidate document filter.")
    latest_parser.add_argument("--candidate-name", default=None, help="Candidate name LIKE filter.")
    latest_parser.add_argument("--limit", type=int, default=25, help="Max rows.")
    add_output_format_arg(latest_parser)

    diff_parser = insights_subparsers.add_parser(
        "historical-differences",
        help="Compare latest successful run against previous successful run.",
    )
    diff_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    diff_parser.add_argument("--route", default=None, help="Route key filter.")
    diff_parser.add_argument("--region", default=None, help="Region name filter.")
    diff_parser.add_argument(
        "--kind",
        default="candidate",
        choices=["candidate", "party_list", "blank_vote", "null_vote", "all"],
        help="Result kind filter.",
    )
    diff_parser.add_argument("--candidate-document", default=None, help="Candidate document filter.")
    diff_parser.add_argument("--candidate-name", default=None, help="Candidate name LIKE filter.")
    diff_parser.add_argument("--limit", type=int, default=30, help="Max rows.")
    add_output_format_arg(diff_parser)

    top_parser = insights_subparsers.add_parser(
        "top-regions-by-candidate",
        help="Top N regions for a given candidate in latest run.",
    )
    top_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    top_parser.add_argument(
        "--route",
        required=True,
        help="Route key (required).",
    )
    top_parser.add_argument("--candidate-document", default=None, help="Candidate document.")
    top_parser.add_argument("--candidate-name", default=None, help="Candidate name LIKE filter.")
    top_parser.add_argument("--limit", type=int, default=5, help="Max rows.")
    add_output_format_arg(top_parser)

    top_general_parser = insights_subparsers.add_parser(
        "top-candidates-general",
        help="Top N general/national candidates with actas metrics.",
    )
    top_general_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    top_general_parser.add_argument(
        "--route",
        required=True,
        help="Route key (required).",
    )
    top_general_parser.add_argument("--limit", type=int, default=5, help="Max rows.")
    add_output_format_arg(top_general_parser)

    least_parser = insights_subparsers.add_parser(
        "least-vote-regions",
        help="Regions with least total votes in latest run.",
    )
    least_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    least_parser.add_argument("--route", default=None, help="Route key filter.")
    least_parser.add_argument("--limit", type=int, default=10, help="Max rows.")
    add_output_format_arg(least_parser)

    leaderboard_parser = insights_subparsers.add_parser(
        "leaderboard-snapshots",
        help="Leader and runner-up snapshot by region for latest run.",
    )
    leaderboard_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    leaderboard_parser.add_argument("--route", default=None, help="Route key filter.")
    leaderboard_parser.add_argument("--limit", type=int, default=25, help="Max rows.")
    add_output_format_arg(leaderboard_parser)

    volatility_parser = insights_subparsers.add_parser(
        "volatility-hotspots",
        help="Regions with strongest two-run candidate composition swing.",
    )
    volatility_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    volatility_parser.add_argument("--route", default=None, help="Route key filter.")
    volatility_parser.add_argument("--limit", type=int, default=25, help="Max rows.")
    add_output_format_arg(volatility_parser)

    concentration_parser = insights_subparsers.add_parser(
        "concentration-index",
        help="Candidate concentration metrics (top2 share, HHI, effective count).",
    )
    concentration_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    concentration_parser.add_argument("--route", default=None, help="Route key filter.")
    concentration_parser.add_argument("--limit", type=int, default=25, help="Max rows.")
    add_output_format_arg(concentration_parser)

    momentum_parser = insights_subparsers.add_parser(
        "momentum-by-region",
        help="Top gainer and loser by region between latest two runs.",
    )
    momentum_parser.add_argument(
        "--db",
        default="data/onpe_results.db",
        help="SQLite DB path (default: data/onpe_results.db)",
    )
    momentum_parser.add_argument("--route", default=None, help="Route key filter.")
    momentum_parser.add_argument("--limit", type=int, default=25, help="Max rows.")
    add_output_format_arg(momentum_parser)

    return parser.parse_args(argv)


def select_routes(route_keys: list[str] | None):
    if not route_keys:
        return ROUTES

    by_key = {route.key: route for route in ROUTES}
    selected = []

    for key in route_keys:
        if key not in by_key:
            valid = ", ".join(sorted(by_key))
            raise ValueError(f"Unknown route key '{key}'. Valid keys: {valid}")
        selected.append(by_key[key])

    return selected


def run_scraper(db_path: str, sleep_seconds: float, route_keys: list[str] | None) -> int:
    routes = select_routes(route_keys)
    db = ScraperDB(Path(db_path))
    client = OnpeApiClient()
    scraper = OnpeRegionalScraper(client=client, db=db, sleep_seconds=sleep_seconds)

    try:
        run_id = scraper.scrape(routes)
        total_rows = db.count_endpoint_rows(run_id)
        candidate_rows = db.count_candidate_result_rows(run_id)
        print(
            f"run_id={run_id} routes={len(routes)} responses={total_rows} "
            f"candidate_results={candidate_rows} db={db_path}"
        )
        return run_id
    finally:
        db.close()


def run_insights(args: argparse.Namespace) -> None:
    service = InsightsService(Path(args.db))
    try:
        if args.insight_command == "latest-results":
            rows = service.latest_results(
                route_key=args.route,
                region_name=args.region,
                result_kind=args.kind,
                candidate_document=args.candidate_document,
                candidate_name=args.candidate_name,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "historical-differences":
            rows = service.historical_differences(
                route_key=args.route,
                region_name=args.region,
                result_kind=args.kind,
                candidate_document=args.candidate_document,
                candidate_name=args.candidate_name,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "top-regions-by-candidate":
            rows = service.top_regions_by_candidate(
                route_key=args.route,
                candidate_document=args.candidate_document,
                candidate_name=args.candidate_name,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "top-candidates-general":
            rows = service.top_candidates_general(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "least-vote-regions":
            rows = service.least_vote_regions(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "leaderboard-snapshots":
            rows = service.leaderboard_snapshots(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "volatility-hotspots":
            rows = service.volatility_hotspots(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "concentration-index":
            rows = service.concentration_index(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        if args.insight_command == "momentum-by-region":
            rows = service.momentum_by_region(
                route_key=args.route,
                limit=args.limit,
            )
            print_rows(rows, args.output_format)
            return

        raise ValueError(f"Unknown insight command: {args.insight_command}")
    finally:
        service.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        if args.command == "scrape":
            run_scraper(
                db_path=args.db,
                sleep_seconds=args.sleep,
                route_keys=args.routes,
            )
        elif args.command == "insights":
            run_insights(args)
        else:
            raise ValueError(f"Unknown command: {args.command}")
        return 0
    except Exception as exc:
        print(f"command_failed error={exc}", file=sys.stderr)
        return 1
