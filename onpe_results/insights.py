from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No rows found.")
        return

    columns = list(rows[0].keys())
    widths = {col: len(col) for col in columns}

    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(_fmt(row.get(col))))

    header = " | ".join(col.ljust(widths[col]) for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)
    print(header)
    print(sep)

    for row in rows:
        print(" | ".join(_fmt(row.get(col)).ljust(widths[col]) for col in columns))


def print_json(rows: list[dict[str, Any]]) -> None:
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def print_rows(rows: list[dict[str, Any]], output_format: str) -> None:
    if output_format == "json":
        print_json(rows)
        return
    print_table(rows)


class InsightsService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._route_ts_cache: dict[int, dict[str, int | None]] = {}

    def close(self) -> None:
        self.conn.close()

    def _latest_success_run_id(self, route_key: str | None = None) -> int:
        if route_key is None:
            row = self.conn.execute(
                "SELECT id FROM scrape_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT sr.id
                FROM scrape_runs sr
                JOIN routes r ON r.run_id = sr.id
                WHERE sr.status = 'success' AND r.route_key = ?
                ORDER BY sr.id DESC
                LIMIT 1
                """,
                (route_key,),
            ).fetchone()

        if row is None:
            if route_key:
                raise ValueError(f"No successful runs found for route '{route_key}'.")
            raise ValueError("No successful runs found.")
        return int(row["id"])

    def _two_latest_success_runs(self, route_key: str | None = None) -> tuple[int, int]:
        if route_key is None:
            rows = self.conn.execute(
                "SELECT id FROM scrape_runs WHERE status = 'success' ORDER BY id DESC LIMIT 2"
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT sr.id
                FROM scrape_runs sr
                JOIN routes r ON r.run_id = sr.id
                WHERE sr.status = 'success' AND r.route_key = ?
                GROUP BY sr.id
                ORDER BY sr.id DESC
                LIMIT 2
                """,
                (route_key,),
            ).fetchall()

        if len(rows) < 2:
            if route_key:
                raise ValueError(
                    f"Need at least 2 successful runs for route '{route_key}' to compute historical differences."
                )
            raise ValueError("Need at least 2 successful runs for historical differences.")

        return int(rows[0]["id"]), int(rows[1]["id"])

    def _route_api_timestamp_map(self, run_id: int) -> dict[str, int | None]:
        cached = self._route_ts_cache.get(run_id)
        if cached is not None:
            return cached

        rows = self.conn.execute(
            """
            SELECT
                route_key,
                MAX(fecha_actualizacion) AS api_timestamp_ms
            FROM regional_summaries
            WHERE run_id = ?
              AND endpoint_key = 'regional_summary_totales'
            GROUP BY route_key
            """,
            (run_id,),
        ).fetchall()
        result = {str(row["route_key"]): row["api_timestamp_ms"] for row in rows}
        self._route_ts_cache[run_id] = result
        return result

    def _attach_api_timestamp(
        self,
        rows: list[dict[str, Any]],
        *,
        run_id_field: str = "run_id",
        route_key_field: str = "route_key",
        output_field: str = "api_timestamp_ms",
    ) -> list[dict[str, Any]]:
        for row in rows:
            if row.get(output_field) is not None:
                continue
            run_id = row.get(run_id_field)
            route_key = row.get(route_key_field)
            if not isinstance(run_id, int) or not isinstance(route_key, str):
                row[output_field] = None
                continue
            row[output_field] = self._route_api_timestamp_map(run_id).get(route_key)
        return rows

    def _attach_dual_api_timestamps(
        self,
        rows: list[dict[str, Any]],
        *,
        current_run_field: str = "current_run",
        previous_run_field: str = "previous_run",
        route_key_field: str = "route_key",
        current_output_field: str = "current_api_timestamp_ms",
        previous_output_field: str = "previous_api_timestamp_ms",
    ) -> list[dict[str, Any]]:
        for row in rows:
            current_run = row.get(current_run_field)
            previous_run = row.get(previous_run_field)
            route_key = row.get(route_key_field)

            if isinstance(current_run, int) and isinstance(route_key, str):
                row[current_output_field] = self._route_api_timestamp_map(current_run).get(route_key)
            else:
                row[current_output_field] = None

            if isinstance(previous_run, int) and isinstance(route_key, str):
                row[previous_output_field] = self._route_api_timestamp_map(previous_run).get(route_key)
            else:
                row[previous_output_field] = None
        return rows

    def latest_results(
        self,
        *,
        route_key: str | None,
        region_name: str | None,
        result_kind: str,
        candidate_document: str | None,
        candidate_name: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        run_id = self._latest_success_run_id(route_key)

        where = ["run_id = ?", "endpoint_key = 'regional_participants'"]
        params: list[Any] = [run_id]

        if route_key:
            where.append("route_key = ?")
            params.append(route_key)

        if region_name:
            where.append("region_name = ?")
            params.append(region_name)

        if result_kind != "all":
            where.append("result_kind = ?")
            params.append(result_kind)

        if candidate_document:
            where.append("candidate_document = ?")
            params.append(candidate_document)

        if candidate_name:
            where.append("candidate_name LIKE ?")
            params.append(f"%{candidate_name}%")

        params.append(limit)

        query = f"""
            SELECT
                run_id,
                route_key,
                region_name,
                result_kind,
                group_name,
                candidate_name,
                candidate_document,
                total_votes_validos,
                pct_votes_validos,
                pct_votes_emitidos
            FROM v_candidate_results_llm
            WHERE {' AND '.join(where)}
            ORDER BY total_votes_validos DESC, route_key, region_name
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def historical_differences(
        self,
        *,
        route_key: str | None,
        region_name: str | None,
        result_kind: str,
        candidate_document: str | None,
        candidate_name: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        current_run, previous_run = self._two_latest_success_runs(route_key)

        where_common = ["endpoint_key = 'regional_participants'"]
        params: list[Any] = []

        if route_key:
            where_common.append("route_key = ?")
            params.append(route_key)

        if region_name:
            where_common.append("region_name = ?")
            params.append(region_name)

        if result_kind != "all":
            where_common.append("result_kind = ?")
            params.append(result_kind)

        if candidate_document:
            where_common.append("candidate_document = ?")
            params.append(candidate_document)

        if candidate_name:
            where_common.append("candidate_name LIKE ?")
            params.append(f"%{candidate_name}%")

        where_sql = " AND ".join(where_common)

        query = f"""
            WITH cur AS (
                SELECT *
                FROM v_candidate_results_llm
                WHERE run_id = ? AND {where_sql}
            ),
            prev AS (
                SELECT *
                FROM v_candidate_results_llm
                WHERE run_id = ? AND {where_sql}
            )
            SELECT
                cur.route_key,
                cur.region_name,
                cur.result_kind,
                cur.group_name,
                cur.candidate_name,
                cur.candidate_document,
                cur.total_votes_validos AS votes_current,
                prev.total_votes_validos AS votes_previous,
                (cur.total_votes_validos - COALESCE(prev.total_votes_validos, 0)) AS delta_votes,
                cur.pct_votes_validos AS pct_current,
                prev.pct_votes_validos AS pct_previous,
                (cur.pct_votes_validos - COALESCE(prev.pct_votes_validos, 0)) AS delta_pct
            FROM cur
            LEFT JOIN prev
              ON prev.route_key = cur.route_key
             AND IFNULL(prev.region_code, '') = IFNULL(cur.region_code, '')
             AND IFNULL(prev.result_kind, '') = IFNULL(cur.result_kind, '')
             AND IFNULL(prev.group_code, '') = IFNULL(cur.group_code, '')
             AND IFNULL(prev.group_name, '') = IFNULL(cur.group_name, '')
             AND IFNULL(prev.candidate_document, '') = IFNULL(cur.candidate_document, '')
             AND IFNULL(prev.candidate_name, '') = IFNULL(cur.candidate_name, '')
            ORDER BY ABS(delta_votes) DESC, cur.route_key, cur.region_name
            LIMIT ?
        """

        bound: list[Any] = [current_run, *params, previous_run, *params, limit]
        rows = self.conn.execute(query, bound).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["current_run"] = current_run
            item["previous_run"] = previous_run
            result.append(item)
        return self._attach_dual_api_timestamps(result)

    def leaderboard_snapshots(
        self,
        *,
        route_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        run_id = self._latest_success_run_id(route_key)

        where = ["run_id = ?", "endpoint_key = 'regional_participants'", "result_kind = 'candidate'"]
        params: list[Any] = [run_id]

        if route_key:
            where.append("route_key = ?")
            params.append(route_key)

        params.append(limit)

        query = f"""
            WITH ranked AS (
                SELECT
                    run_id,
                    route_key,
                    region_code,
                    region_name,
                    group_name,
                    candidate_name,
                    candidate_document,
                    total_votes_validos,
                    pct_votes_validos,
                    ROW_NUMBER() OVER (
                        PARTITION BY route_key, IFNULL(region_code, region_name)
                        ORDER BY total_votes_validos DESC, candidate_name
                    ) AS rn
                FROM v_candidate_results_llm
                WHERE {' AND '.join(where)}
            )
            SELECT
                run_id,
                route_key,
                region_name,
                MAX(CASE WHEN rn = 1 THEN group_name END) AS leader_group,
                MAX(CASE WHEN rn = 1 THEN candidate_name END) AS leader_candidate,
                MAX(CASE WHEN rn = 1 THEN candidate_document END) AS leader_document,
                MAX(CASE WHEN rn = 1 THEN total_votes_validos END) AS leader_votes,
                MAX(CASE WHEN rn = 1 THEN pct_votes_validos END) AS leader_pct,
                MAX(CASE WHEN rn = 2 THEN group_name END) AS runner_up_group,
                MAX(CASE WHEN rn = 2 THEN candidate_name END) AS runner_up_candidate,
                MAX(CASE WHEN rn = 2 THEN candidate_document END) AS runner_up_document,
                MAX(CASE WHEN rn = 2 THEN total_votes_validos END) AS runner_up_votes,
                MAX(CASE WHEN rn = 2 THEN pct_votes_validos END) AS runner_up_pct,
                (
                    COALESCE(MAX(CASE WHEN rn = 1 THEN total_votes_validos END), 0)
                    - COALESCE(MAX(CASE WHEN rn = 2 THEN total_votes_validos END), 0)
                ) AS margin_votes,
                (
                    COALESCE(MAX(CASE WHEN rn = 1 THEN pct_votes_validos END), 0)
                    - COALESCE(MAX(CASE WHEN rn = 2 THEN pct_votes_validos END), 0)
                ) AS margin_pct
            FROM ranked
            WHERE rn <= 2
            GROUP BY run_id, route_key, region_code, region_name
            ORDER BY route_key, region_name
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def top_regions_by_candidate(
        self,
        *,
        route_key: str,
        candidate_document: str | None,
        candidate_name: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not candidate_document and not candidate_name:
            raise ValueError("Provide --candidate-document or --candidate-name.")

        run_id = self._latest_success_run_id(route_key)

        where = [
            "run_id = ?",
            "endpoint_key = 'regional_participants'",
            "result_kind = 'candidate'",
            "route_key = ?",
        ]
        params: list[Any] = [run_id, route_key]

        if candidate_document:
            where.append("candidate_document = ?")
            params.append(candidate_document)

        if candidate_name:
            where.append("candidate_name LIKE ?")
            params.append(f"%{candidate_name}%")

        params.append(limit)

        query = f"""
            SELECT
                run_id,
                route_key,
                region_name,
                group_name,
                candidate_name,
                candidate_document,
                total_votes_validos,
                pct_votes_validos,
                pct_votes_emitidos
            FROM v_candidate_results_llm
            WHERE {' AND '.join(where)}
            ORDER BY total_votes_validos DESC
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def top_candidates_general(
        self,
        *,
        route_key: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        run_id = self._latest_success_run_id(route_key)

        query = """
            WITH candidate_totals AS (
                SELECT
                    run_id,
                    route_key,
                    group_name,
                    candidate_name,
                    candidate_document,
                    SUM(COALESCE(total_votes_validos, 0)) AS votes_total
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND route_key = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
                GROUP BY run_id, route_key, group_name, candidate_name, candidate_document
            ),
            election_totals AS (
                SELECT
                    SUM(COALESCE(total_votes_validos, 0)) AS valid_votes_total
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND route_key = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
            ),
            actas_totals AS (
                SELECT
                    SUM(COALESCE(contabilizadas, 0)) AS actas_contabilizadas_num,
                    SUM(COALESCE(total_actas, 0)) AS total_actas
                FROM regional_summaries
                WHERE run_id = ?
                  AND route_key = ?
                  AND endpoint_key = 'regional_summary_totales'
            )
            SELECT
                c.run_id,
                c.route_key,
                c.group_name,
                c.candidate_name,
                c.candidate_document,
                c.votes_total,
                CASE
                    WHEN e.valid_votes_total > 0
                    THEN (c.votes_total * 100.0) / e.valid_votes_total
                    ELSE NULL
                END AS pct_votes_validos_total,
                a.actas_contabilizadas_num,
                a.total_actas,
                CASE
                    WHEN a.total_actas > 0
                    THEN (a.actas_contabilizadas_num * 100.0) / a.total_actas
                    ELSE NULL
                END AS actas_contabilizadas_pct
            FROM candidate_totals c
            CROSS JOIN election_totals e
            CROSS JOIN actas_totals a
            ORDER BY c.votes_total DESC, c.candidate_name
            LIMIT ?
        """

        rows = self.conn.execute(
            query,
            (run_id, route_key, run_id, route_key, run_id, route_key, limit),
        ).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def least_vote_regions(
        self,
        *,
        route_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        run_id = self._latest_success_run_id(route_key)

        where = ["run_id = ?", "endpoint_key = 'regional_summary_totales'"]
        params: list[Any] = [run_id]

        if route_key:
            where.append("route_key = ?")
            params.append(route_key)

        params.append(limit)

        query = f"""
            SELECT
                run_id,
                route_key,
                region_name,
                total_votos_emitidos,
                total_votos_validos,
                participacion_ciudadana,
                actas_contabilizadas,
                fecha_actualizacion AS api_timestamp_ms
            FROM regional_summaries
            WHERE {' AND '.join(where)}
            ORDER BY total_votos_emitidos ASC
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def concentration_index(
        self,
        *,
        route_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        run_id = self._latest_success_run_id(route_key)

        where = ["run_id = ?", "endpoint_key = 'regional_participants'", "result_kind = 'candidate'"]
        params: list[Any] = [run_id]

        if route_key:
            where.append("route_key = ?")
            params.append(route_key)

        params.append(limit)

        query = f"""
            WITH ranked AS (
                SELECT
                    run_id,
                    route_key,
                    region_code,
                    region_name,
                    group_name,
                    candidate_name,
                    pct_votes_validos,
                    ROW_NUMBER() OVER (
                        PARTITION BY route_key, IFNULL(region_code, region_name)
                        ORDER BY pct_votes_validos DESC, candidate_name
                    ) AS rn
                FROM v_candidate_results_llm
                WHERE {' AND '.join(where)}
            )
            SELECT
                run_id,
                route_key,
                region_name,
                COUNT(*) AS candidate_count,
                MAX(CASE WHEN rn = 1 THEN candidate_name END) AS leader_candidate,
                MAX(CASE WHEN rn = 1 THEN group_name END) AS leader_group,
                MAX(CASE WHEN rn = 1 THEN pct_votes_validos END) AS top1_pct,
                MAX(CASE WHEN rn = 2 THEN pct_votes_validos END) AS top2_pct,
                (
                    COALESCE(MAX(CASE WHEN rn = 1 THEN pct_votes_validos END), 0)
                    + COALESCE(MAX(CASE WHEN rn = 2 THEN pct_votes_validos END), 0)
                ) AS top2_share_pct,
                SUM((pct_votes_validos / 100.0) * (pct_votes_validos / 100.0)) AS hhi_index,
                CASE
                    WHEN SUM((pct_votes_validos / 100.0) * (pct_votes_validos / 100.0)) > 0
                    THEN 1.0 / SUM((pct_votes_validos / 100.0) * (pct_votes_validos / 100.0))
                    ELSE NULL
                END AS effective_candidate_count
            FROM ranked
            GROUP BY run_id, route_key, region_code, region_name
            ORDER BY hhi_index DESC, route_key, region_name
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        return self._attach_api_timestamp([dict(r) for r in rows])

    def volatility_hotspots(
        self,
        *,
        route_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        current_run, previous_run = self._two_latest_success_runs(route_key)

        route_clause = ""
        params: list[Any] = [current_run]
        if route_key:
            route_clause = " AND route_key = ?"
            params.append(route_key)

        params.append(previous_run)
        if route_key:
            params.append(route_key)

        params.append(limit)

        query = f"""
            WITH cur AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    IFNULL(candidate_document, '') AS candidate_document,
                    IFNULL(candidate_name, '') AS candidate_name,
                    IFNULL(group_code, '') AS group_code,
                    IFNULL(group_name, '') AS group_name,
                    IFNULL(total_votes_validos, 0) AS votes,
                    IFNULL(pct_votes_validos, 0) AS pct
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
                  {route_clause}
            ),
            prev AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    IFNULL(candidate_document, '') AS candidate_document,
                    IFNULL(candidate_name, '') AS candidate_name,
                    IFNULL(group_code, '') AS group_code,
                    IFNULL(group_name, '') AS group_name,
                    IFNULL(total_votes_validos, 0) AS votes,
                    IFNULL(pct_votes_validos, 0) AS pct
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
                  {route_clause}
            ),
            keys AS (
                SELECT route_key, region_code, region_name, candidate_document, candidate_name, group_code, group_name FROM cur
                UNION
                SELECT route_key, region_code, region_name, candidate_document, candidate_name, group_code, group_name FROM prev
            ),
            joined AS (
                SELECT
                    k.route_key,
                    k.region_code,
                    k.region_name,
                    k.candidate_name,
                    k.group_name,
                    COALESCE(c.votes, 0) AS votes_current,
                    COALESCE(p.votes, 0) AS votes_previous,
                    COALESCE(c.pct, 0) AS pct_current,
                    COALESCE(p.pct, 0) AS pct_previous,
                    (COALESCE(c.pct, 0) - COALESCE(p.pct, 0)) AS delta_pct,
                    (COALESCE(c.votes, 0) - COALESCE(p.votes, 0)) AS delta_votes
                FROM keys k
                LEFT JOIN cur c
                  ON c.route_key = k.route_key
                 AND IFNULL(c.region_code, '') = IFNULL(k.region_code, '')
                 AND c.candidate_document = k.candidate_document
                 AND c.candidate_name = k.candidate_name
                 AND c.group_code = k.group_code
                 AND c.group_name = k.group_name
                LEFT JOIN prev p
                  ON p.route_key = k.route_key
                 AND IFNULL(p.region_code, '') = IFNULL(k.region_code, '')
                 AND p.candidate_document = k.candidate_document
                 AND p.candidate_name = k.candidate_name
                 AND p.group_code = k.group_code
                 AND p.group_name = k.group_name
            ),
            region_agg AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    SUM(ABS(delta_pct)) / 2.0 AS swing_index_pct,
                    SUM(ABS(delta_votes)) / 2.0 AS swing_votes,
                    MAX(ABS(delta_pct)) AS max_candidate_shift_pct
                FROM joined
                GROUP BY route_key, region_code, region_name
            ),
            max_shift AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    candidate_name,
                    group_name,
                    delta_pct,
                    ROW_NUMBER() OVER (
                        PARTITION BY route_key, IFNULL(region_code, region_name)
                        ORDER BY ABS(delta_pct) DESC, candidate_name
                    ) AS rn
                FROM joined
            )
            SELECT
                a.route_key,
                a.region_name,
                a.swing_index_pct,
                a.swing_votes,
                a.max_candidate_shift_pct,
                m.candidate_name AS max_shift_candidate,
                m.group_name AS max_shift_group,
                m.delta_pct AS max_shift_delta_pct
            FROM region_agg a
            LEFT JOIN max_shift m
              ON m.route_key = a.route_key
             AND IFNULL(m.region_code, '') = IFNULL(a.region_code, '')
             AND m.rn = 1
            ORDER BY a.swing_index_pct DESC, a.swing_votes DESC
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["current_run"] = current_run
            item["previous_run"] = previous_run
            result.append(item)
        return self._attach_dual_api_timestamps(result)

    def momentum_by_region(
        self,
        *,
        route_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        current_run, previous_run = self._two_latest_success_runs(route_key)

        route_clause = ""
        params: list[Any] = [current_run]
        if route_key:
            route_clause = " AND route_key = ?"
            params.append(route_key)

        params.append(previous_run)
        if route_key:
            params.append(route_key)

        params.append(limit)

        query = f"""
            WITH cur AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    IFNULL(candidate_document, '') AS candidate_document,
                    IFNULL(candidate_name, '') AS candidate_name,
                    IFNULL(group_code, '') AS group_code,
                    IFNULL(group_name, '') AS group_name,
                    IFNULL(total_votes_validos, 0) AS votes,
                    IFNULL(pct_votes_validos, 0) AS pct
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
                  {route_clause}
            ),
            prev AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    IFNULL(candidate_document, '') AS candidate_document,
                    IFNULL(candidate_name, '') AS candidate_name,
                    IFNULL(group_code, '') AS group_code,
                    IFNULL(group_name, '') AS group_name,
                    IFNULL(total_votes_validos, 0) AS votes,
                    IFNULL(pct_votes_validos, 0) AS pct
                FROM v_candidate_results_llm
                WHERE run_id = ?
                  AND endpoint_key = 'regional_participants'
                  AND result_kind = 'candidate'
                  {route_clause}
            ),
            keys AS (
                SELECT route_key, region_code, region_name, candidate_document, candidate_name, group_code, group_name FROM cur
                UNION
                SELECT route_key, region_code, region_name, candidate_document, candidate_name, group_code, group_name FROM prev
            ),
            joined AS (
                SELECT
                    k.route_key,
                    k.region_code,
                    k.region_name,
                    k.candidate_name,
                    k.group_name,
                    (COALESCE(c.votes, 0) - COALESCE(p.votes, 0)) AS delta_votes,
                    (COALESCE(c.pct, 0) - COALESCE(p.pct, 0)) AS delta_pct
                FROM keys k
                LEFT JOIN cur c
                  ON c.route_key = k.route_key
                 AND IFNULL(c.region_code, '') = IFNULL(k.region_code, '')
                 AND c.candidate_document = k.candidate_document
                 AND c.candidate_name = k.candidate_name
                 AND c.group_code = k.group_code
                 AND c.group_name = k.group_name
                LEFT JOIN prev p
                  ON p.route_key = k.route_key
                 AND IFNULL(p.region_code, '') = IFNULL(k.region_code, '')
                 AND p.candidate_document = k.candidate_document
                 AND p.candidate_name = k.candidate_name
                 AND p.group_code = k.group_code
                 AND p.group_name = k.group_name
            ),
            gainers AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    candidate_name,
                    group_name,
                    delta_votes,
                    delta_pct,
                    ROW_NUMBER() OVER (
                        PARTITION BY route_key, IFNULL(region_code, region_name)
                        ORDER BY delta_pct DESC, delta_votes DESC, candidate_name
                    ) AS rn
                FROM joined
            ),
            losers AS (
                SELECT
                    route_key,
                    region_code,
                    region_name,
                    candidate_name,
                    group_name,
                    delta_votes,
                    delta_pct,
                    ROW_NUMBER() OVER (
                        PARTITION BY route_key, IFNULL(region_code, region_name)
                        ORDER BY delta_pct ASC, delta_votes ASC, candidate_name
                    ) AS rn
                FROM joined
            )
            SELECT
                g.route_key,
                g.region_name,
                g.candidate_name AS top_gainer_candidate,
                g.group_name AS top_gainer_group,
                g.delta_votes AS top_gainer_delta_votes,
                g.delta_pct AS top_gainer_delta_pct,
                l.candidate_name AS top_loser_candidate,
                l.group_name AS top_loser_group,
                l.delta_votes AS top_loser_delta_votes,
                l.delta_pct AS top_loser_delta_pct
            FROM gainers g
            LEFT JOIN losers l
              ON l.route_key = g.route_key
             AND IFNULL(l.region_code, '') = IFNULL(g.region_code, '')
             AND l.rn = 1
            WHERE g.rn = 1
            ORDER BY g.delta_pct DESC, g.delta_votes DESC
            LIMIT ?
        """

        rows = self.conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["current_run"] = current_run
            item["previous_run"] = previous_run
            result.append(item)
        return self._attach_dual_api_timestamps(result)
