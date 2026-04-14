from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import ApiResult, RouteConfig, Region
from .normalizer import ResponseNormalizer
from .utils import to_json, utc_now_iso


class ScraperDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self.normalizer = ResponseNormalizer(self.conn)

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scrape_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                page_url TEXT NOT NULL,
                election_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(run_id, route_key)
            );

            CREATE TABLE IF NOT EXISTS regions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                region_code TEXT NOT NULL,
                region_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(run_id, route_key, region_code)
            );

            CREATE TABLE IF NOT EXISTS endpoint_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                region_code TEXT,
                region_name TEXT,
                endpoint_key TEXT NOT NULL,
                request_url TEXT,
                http_status INTEGER,
                ok INTEGER NOT NULL,
                fetched_at TEXT NOT NULL,
                response_json TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS political_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_key TEXT NOT NULL,
                group_code TEXT NOT NULL,
                group_name TEXT NOT NULL,
                first_seen_run_id INTEGER NOT NULL,
                UNIQUE(route_key, group_code, group_name)
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_key TEXT NOT NULL,
                candidate_document TEXT NOT NULL,
                candidate_name TEXT NOT NULL,
                first_seen_run_id INTEGER NOT NULL,
                UNIQUE(route_key, candidate_document, candidate_name)
            );

            CREATE TABLE IF NOT EXISTS candidate_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                election_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                endpoint_key TEXT NOT NULL,
                region_code TEXT,
                region_name TEXT,
                row_order INTEGER NOT NULL,
                result_kind TEXT NOT NULL,
                group_id INTEGER,
                candidate_id INTEGER,
                total_votes_validos REAL,
                pct_votes_validos REAL,
                pct_votes_emitidos REAL,
                total_candidates INTEGER,
                raw_item_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS regional_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                election_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                endpoint_key TEXT NOT NULL,
                region_code TEXT,
                region_name TEXT,
                actas_contabilizadas REAL,
                contabilizadas INTEGER,
                total_actas INTEGER,
                participacion_ciudadana REAL,
                actas_enviadas_jee REAL,
                enviadas_jee INTEGER,
                actas_pendientes_jee REAL,
                pendientes_jee INTEGER,
                fecha_actualizacion INTEGER,
                id_ubigeo_departamento TEXT,
                id_ubigeo_provincia TEXT,
                id_ubigeo_distrito TEXT,
                id_ubigeo_distrito_electoral TEXT,
                total_votos_emitidos REAL,
                total_votos_validos REAL,
                pct_votos_emitidos REAL,
                pct_votos_validos REAL,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mesa_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                election_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                endpoint_key TEXT NOT NULL,
                region_code TEXT,
                region_name TEXT,
                mesas_instaladas INTEGER,
                mesas_no_instaladas INTEGER,
                mesas_pendientes INTEGER,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_endpoint_run
                ON endpoint_responses(run_id);
            CREATE INDEX IF NOT EXISTS idx_endpoint_route
                ON endpoint_responses(route_key);
            CREATE INDEX IF NOT EXISTS idx_endpoint_region
                ON endpoint_responses(region_code);

            CREATE INDEX IF NOT EXISTS idx_candidate_results_run
                ON candidate_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_candidate_results_route
                ON candidate_results(route_key);
            CREATE INDEX IF NOT EXISTS idx_candidate_results_region
                ON candidate_results(region_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_results_natural
                ON candidate_results(run_id, route_key, endpoint_key, ifnull(region_code, ''), row_order);
            CREATE INDEX IF NOT EXISTS idx_regional_summaries_run
                ON regional_summaries(run_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_regional_summaries_natural
                ON regional_summaries(run_id, route_key, endpoint_key, ifnull(region_code, ''));
            CREATE INDEX IF NOT EXISTS idx_mesa_status_run
                ON mesa_status(run_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_mesa_status_natural
                ON mesa_status(run_id, route_key, endpoint_key, ifnull(region_code, ''));

            CREATE VIEW IF NOT EXISTS v_candidate_results_llm AS
            SELECT
                cr.id,
                cr.run_id,
                cr.route_key,
                cr.election_id,
                cr.mode,
                cr.endpoint_key,
                cr.region_code,
                cr.region_name,
                cr.row_order,
                cr.result_kind,
                pg.group_code,
                pg.group_name,
                c.candidate_document,
                c.candidate_name,
                cr.total_votes_validos,
                cr.pct_votes_validos,
                cr.pct_votes_emitidos,
                cr.total_candidates,
                cr.fetched_at
            FROM candidate_results cr
            LEFT JOIN political_groups pg ON pg.id = cr.group_id
            LEFT JOIN candidates c ON c.id = cr.candidate_id;
            """
        )
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO scrape_runs(started_at, status) VALUES(?, ?)",
            (utc_now_iso(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE scrape_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?",
            (utc_now_iso(), status, error, run_id),
        )
        self.conn.commit()

    def insert_route(self, run_id: int, route: RouteConfig) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO routes(
                run_id, route_key, page_url, election_id, mode, fetched_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                route.key,
                route.page_url,
                route.election_id,
                route.mode,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def insert_region(self, run_id: int, route: RouteConfig, region: Region) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO regions(
                run_id, route_key, region_code, region_name, raw_payload, fetched_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                route.key,
                region.code,
                region.name,
                to_json(region.raw_payload),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def insert_response(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        result: ApiResult,
        region: Region | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO endpoint_responses(
                run_id, route_key, region_code, region_name, endpoint_key,
                request_url, http_status, ok, fetched_at, response_json, error
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                route.key,
                region.code if region else None,
                region.name if region else None,
                endpoint_key,
                result.request_url,
                result.status_code,
                1 if result.ok else 0,
                utc_now_iso(),
                to_json(result.payload) if result.payload is not None else None,
                result.error,
            ),
        )
        self.conn.commit()

    def normalize_endpoint_result(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        payload: Any,
        region: Region | None,
    ) -> None:
        self.normalizer.normalize_endpoint_result(
            run_id=run_id,
            route=route,
            endpoint_key=endpoint_key,
            payload=payload,
            region=region,
        )

    def count_endpoint_rows(self, run_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM endpoint_responses WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        return int(row["n"])

    def count_candidate_result_rows(self, run_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM candidate_results WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        return int(row["n"])
