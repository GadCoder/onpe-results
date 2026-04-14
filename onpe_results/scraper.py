from __future__ import annotations

import time
from typing import Any, Iterable

from .client import OnpeApiClient
from .database import ScraperDB
from .models import ApiResult, Region, RouteConfig


class OnpeRegionalScraper:
    def __init__(
        self,
        *,
        client: OnpeApiClient,
        db: ScraperDB,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.client = client
        self.db = db
        self.sleep_seconds = max(0.0, sleep_seconds)

    def scrape(self, routes: Iterable[RouteConfig]) -> int:
        run_id = self.db.start_run()
        try:
            for route in routes:
                self._scrape_route(run_id, route)
            self.db.finish_run(run_id, "success")
            return run_id
        except Exception as exc:
            self.db.finish_run(run_id, "failed", str(exc))
            raise

    def _scrape_route(self, run_id: int, route: RouteConfig) -> None:
        self.db.insert_route(run_id, route)

        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="process_active",
            path="/proceso/proceso-electoral-activo",
            params={},
            region=None,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="process_elections",
            path="/proceso/2/elecciones",
            params={},
            region=None,
        )

        if route.mode == "ambito_geografico":
            self._scrape_route_baseline_ambito(run_id, route)
            regions = self._fetch_departments(run_id, route)
            for region in regions:
                self.db.insert_region(run_id, route, region)
                self._scrape_region_ambito(run_id, route, region)
        elif route.mode == "distrito_electoral":
            self._scrape_route_baseline_distrito(run_id, route)
            regions = self._fetch_distritos(run_id, route)
            for region in regions:
                self.db.insert_region(run_id, route, region)
                self._scrape_region_distrito(run_id, route, region)
        else:
            raise ValueError(f"Unsupported route mode: {route.mode}")

    def _scrape_route_baseline_ambito(self, run_id: int, route: RouteConfig) -> None:
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="baseline_participants",
            path=route.participants_path,
            params={"idEleccion": route.election_id, "tipoFiltro": "eleccion"},
            region=None,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="baseline_mesa_totales",
            path="/mesa/totales",
            params={"tipoFiltro": "eleccion"},
            region=None,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="baseline_summary_totales",
            path="/resumen-general/totales",
            params={"idEleccion": route.election_id, "tipoFiltro": "eleccion"},
            region=None,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="baseline_mapa_calor",
            path="/resumen-general/mapa-calor",
            params={"idEleccion": route.election_id, "tipoFiltro": "total"},
            region=None,
        )

    def _scrape_route_baseline_distrito(self, run_id: int, route: RouteConfig) -> None:
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="baseline_mapa_calor",
            path="/resumen-general/mapa-calor",
            params={
                "codigoAgrupacionPolitica": 0,
                "idAmbitoGeografico": 1,
                "idEleccion": route.election_id,
                "tipoFiltro": "distrito_electoral",
            },
            region=None,
        )

    def _fetch_departments(self, run_id: int, route: RouteConfig) -> list[Region]:
        result = self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regions_catalog_departamentos",
            path="/ubigeos/departamentos",
            params={"idEleccion": route.election_id, "idAmbitoGeografico": 1},
            region=None,
        )

        data = []
        if isinstance(result.payload, dict):
            maybe_data = result.payload.get("data")
            if isinstance(maybe_data, list):
                data = maybe_data

        regions: list[Region] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            code = str(item.get("ubigeo", "")).strip()
            name = str(item.get("nombre", "")).strip()
            if not code or not name:
                continue
            regions.append(Region(code=code, name=name, raw_payload=item))

        return regions

    def _fetch_distritos(self, run_id: int, route: RouteConfig) -> list[Region]:
        result = self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regions_catalog_distritos",
            path="/distrito-electoral/distritos",
            params={},
            region=None,
        )

        data = []
        if isinstance(result.payload, dict):
            maybe_data = result.payload.get("data")
            if isinstance(maybe_data, list):
                data = maybe_data

        regions: list[Region] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_code = item.get("codigo")
            code = str(raw_code).strip() if raw_code is not None else ""
            name = str(item.get("nombre", "")).strip()
            if not code or not name:
                continue
            regions.append(Region(code=code, name=name, raw_payload=item))

        return regions

    def _scrape_region_ambito(self, run_id: int, route: RouteConfig, region: Region) -> None:
        params_common = {
            "tipoFiltro": "ubigeo_nivel_01",
            "idAmbitoGeografico": 1,
            "idEleccion": route.election_id,
        }

        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_participants",
            path=route.participants_path,
            params={**params_common, "ubigeoNivel1": region.code},
            region=region,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_summary_totales",
            path="/resumen-general/totales",
            params={
                **params_common,
                "idUbigeoDepartamento": region.code,
            },
            region=region,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_mapa_calor",
            path="/resumen-general/mapa-calor",
            params={
                **params_common,
                "ubigeoNivel01": region.code,
            },
            region=region,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_mesa_totales",
            path="/mesa/totales",
            params={
                "tipoFiltro": "ubigeo_nivel_01",
                "ubigeoNivel1": region.code,
                "ambitoGeografico": 1,
            },
            region=region,
        )

    def _scrape_region_distrito(self, run_id: int, route: RouteConfig, region: Region) -> None:
        params_common = {
            "idEleccion": route.election_id,
            "tipoFiltro": "distrito_electoral",
            "idDistritoElectoral": region.code,
        }

        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_participants",
            path=route.participants_path,
            params=params_common,
            region=region,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_summary_totales",
            path="/resumen-general/totales",
            params=params_common,
            region=region,
        )
        self._fetch_and_store(
            run_id,
            route,
            endpoint_key="regional_mesa_totales",
            path="/mesa/totales",
            params={
                "ambitoGeografico": 1,
                "distritoElectoral": region.code,
                "tipoFiltro": "distrito_electoral",
            },
            region=region,
        )

    def _fetch_and_store(
        self,
        run_id: int,
        route: RouteConfig,
        *,
        endpoint_key: str,
        path: str,
        params: dict[str, Any],
        region: Region | None,
    ) -> ApiResult:
        result = self.client.get_json(path=path, params=params, referer=route.page_url)
        self.db.insert_response(
            run_id=run_id,
            route=route,
            endpoint_key=endpoint_key,
            result=result,
            region=region,
        )
        if result.ok and result.payload is not None:
            self.db.normalize_endpoint_result(
                run_id=run_id,
                route=route,
                endpoint_key=endpoint_key,
                payload=result.payload,
                region=region,
            )

        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)

        return result
