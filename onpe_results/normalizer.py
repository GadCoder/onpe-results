from __future__ import annotations

import sqlite3
from typing import Any

from .models import RouteConfig, Region
from .utils import clean_text, extract_data, to_float, to_int, to_json, utc_now_iso


class ResponseNormalizer:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def normalize_endpoint_result(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        payload: Any,
        region: Region | None,
    ) -> None:
        data = extract_data(payload)
        if data is None:
            return

        if endpoint_key.endswith("participants") and isinstance(data, list):
            self._normalize_candidate_rows(
                run_id=run_id,
                route=route,
                endpoint_key=endpoint_key,
                rows=data,
                region=region,
            )
            return

        if endpoint_key.endswith("summary_totales") and isinstance(data, dict):
            self._normalize_summary_row(
                run_id=run_id,
                route=route,
                endpoint_key=endpoint_key,
                row=data,
                region=region,
            )
            return

        if endpoint_key.endswith("mesa_totales") and isinstance(data, dict):
            self._normalize_mesa_row(
                run_id=run_id,
                route=route,
                endpoint_key=endpoint_key,
                row=data,
                region=region,
            )

    def _upsert_political_group(
        self,
        *,
        run_id: int,
        route_key: str,
        group_code: str,
        group_name: str,
    ) -> int | None:
        if not group_code and not group_name:
            return None

        normalized_code = group_code
        normalized_name = group_name or f"CODIGO_{group_code or 'SIN_CODIGO'}"

        self.conn.execute(
            """
            INSERT OR IGNORE INTO political_groups(
                route_key, group_code, group_name, first_seen_run_id
            ) VALUES(?, ?, ?, ?)
            """,
            (route_key, normalized_code, normalized_name, run_id),
        )
        row = self.conn.execute(
            """
            SELECT id FROM political_groups
            WHERE route_key = ? AND group_code = ? AND group_name = ?
            LIMIT 1
            """,
            (route_key, normalized_code, normalized_name),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _upsert_candidate(
        self,
        *,
        run_id: int,
        route_key: str,
        candidate_document: str,
        candidate_name: str,
    ) -> int | None:
        if not candidate_document and not candidate_name:
            return None

        normalized_document = candidate_document
        normalized_name = candidate_name or f"DOC_{candidate_document or 'SIN_DOC'}"

        self.conn.execute(
            """
            INSERT OR IGNORE INTO candidates(
                route_key, candidate_document, candidate_name, first_seen_run_id
            ) VALUES(?, ?, ?, ?)
            """,
            (route_key, normalized_document, normalized_name, run_id),
        )
        row = self.conn.execute(
            """
            SELECT id FROM candidates
            WHERE route_key = ? AND candidate_document = ? AND candidate_name = ?
            LIMIT 1
            """,
            (route_key, normalized_document, normalized_name),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _normalize_candidate_rows(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        rows: list[Any],
        region: Region | None,
    ) -> None:
        now = utc_now_iso()
        for row_order, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue

            group_code = clean_text(item.get("codigoAgrupacionPolitica"))
            group_name = clean_text(item.get("nombreAgrupacionPolitica"))
            candidate_document = clean_text(item.get("dniCandidato"))
            candidate_name = clean_text(item.get("nombreCandidato"))

            group_id = self._upsert_political_group(
                run_id=run_id,
                route_key=route.key,
                group_code=group_code,
                group_name=group_name,
            )
            candidate_id = self._upsert_candidate(
                run_id=run_id,
                route_key=route.key,
                candidate_document=candidate_document,
                candidate_name=candidate_name,
            )

            self.conn.execute(
                """
                INSERT OR IGNORE INTO candidate_results(
                    run_id, route_key, election_id, mode, endpoint_key,
                    region_code, region_name, row_order, result_kind,
                    group_id, candidate_id, total_votes_validos,
                    pct_votes_validos, pct_votes_emitidos, total_candidates,
                    raw_item_json, fetched_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    route.key,
                    route.election_id,
                    route.mode,
                    endpoint_key,
                    region.code if region else None,
                    region.name if region else None,
                    row_order,
                    self._classify_result_kind(
                        group_code=group_code,
                        group_name=group_name,
                        candidate_document=candidate_document,
                        candidate_name=candidate_name,
                    ),
                    group_id,
                    candidate_id,
                    to_float(item.get("totalVotosValidos")),
                    to_float(item.get("porcentajeVotosValidos")),
                    to_float(item.get("porcentajeVotosEmitidos")),
                    to_int(item.get("totalCandidatos")),
                    to_json(item),
                    now,
                ),
            )

        self.conn.commit()

    def _normalize_summary_row(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        row: dict[str, Any],
        region: Region | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO regional_summaries(
                run_id, route_key, election_id, mode, endpoint_key,
                region_code, region_name, actas_contabilizadas, contabilizadas,
                total_actas, participacion_ciudadana, actas_enviadas_jee,
                enviadas_jee, actas_pendientes_jee, pendientes_jee,
                fecha_actualizacion, id_ubigeo_departamento, id_ubigeo_provincia,
                id_ubigeo_distrito, id_ubigeo_distrito_electoral,
                total_votos_emitidos, total_votos_validos, pct_votos_emitidos,
                pct_votos_validos, raw_json, fetched_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                route.key,
                route.election_id,
                route.mode,
                endpoint_key,
                region.code if region else None,
                region.name if region else None,
                to_float(row.get("actasContabilizadas")),
                to_int(row.get("contabilizadas")),
                to_int(row.get("totalActas")),
                to_float(row.get("participacionCiudadana")),
                to_float(row.get("actasEnviadasJee")),
                to_int(row.get("enviadasJee")),
                to_float(row.get("actasPendientesJee")),
                to_int(row.get("pendientesJee")),
                to_int(row.get("fechaActualizacion")),
                clean_text(row.get("idUbigeoDepartamento")) or None,
                clean_text(row.get("idUbigeoProvincia")) or None,
                clean_text(row.get("idUbigeoDistrito")) or None,
                clean_text(row.get("idUbigeoDistritoElectoral")) or None,
                to_float(row.get("totalVotosEmitidos")),
                to_float(row.get("totalVotosValidos")),
                to_float(row.get("porcentajeVotosEmitidos")),
                to_float(row.get("porcentajeVotosValidos")),
                to_json(row),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def _normalize_mesa_row(
        self,
        *,
        run_id: int,
        route: RouteConfig,
        endpoint_key: str,
        row: dict[str, Any],
        region: Region | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO mesa_status(
                run_id, route_key, election_id, mode, endpoint_key,
                region_code, region_name, mesas_instaladas, mesas_no_instaladas,
                mesas_pendientes, raw_json, fetched_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                route.key,
                route.election_id,
                route.mode,
                endpoint_key,
                region.code if region else None,
                region.name if region else None,
                to_int(row.get("mesasInstaladas")),
                to_int(row.get("mesasNoInstaladas")),
                to_int(row.get("mesasPendientes")),
                to_json(row),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def _classify_result_kind(
        self,
        *,
        group_code: str,
        group_name: str,
        candidate_document: str,
        candidate_name: str,
    ) -> str:
        group_upper = group_name.upper()
        if group_code == "80" or "BLANCO" in group_upper:
            return "blank_vote"
        if group_code == "81" or "NULO" in group_upper:
            return "null_vote"
        if candidate_document or candidate_name:
            return "candidate"
        if group_code or group_name:
            return "party_list"
        return "other"
