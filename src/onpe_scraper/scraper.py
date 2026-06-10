"""Full-crawl orchestration.

:class:`OnpeScraper` walks the entire public dataset:

1. the active process and its election tree,
2. the full UBIGEO hierarchy,
3. national + Peru/abroad candidate results, and
4. processing/turnout/vote totals at every requested geographic level
   (national -> department -> province -> district).

It is deliberately resumable-friendly: each scope is fetched independently and a
failure on one scope is logged and skipped rather than aborting the run, so a
flaky network during election night never throws away the work already done.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Iterable

from .api import OnpeApi
from .http import OnpeError
from .models import (
    AmbitoGeografico,
    Eleccion,
    Proceso,
    ScopeResult,
    TipoFiltro,
    Ubigeo,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


class GeoLevel(IntEnum):
    """How deep into the geographic hierarchy to sweep totals."""

    NATIONAL = 0
    DEPARTMENT = 1
    PROVINCE = 2
    DISTRICT = 3

    @classmethod
    def parse(cls, value: str | int) -> "GeoLevel":
        if isinstance(value, int):
            return cls(value)
        return {
            "national": cls.NATIONAL,
            "department": cls.DEPARTMENT,
            "province": cls.PROVINCE,
            "district": cls.DISTRICT,
        }[value.lower()]


@dataclass
class ScrapeResult:
    """Everything a crawl produced."""

    proceso: Proceso | None = None
    elecciones: list[Eleccion] = field(default_factory=list)
    ubigeos: list[Ubigeo] = field(default_factory=list)
    scopes: list[ScopeResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OnpeScraper:
    def __init__(self, api: OnpeApi, *, progress: ProgressFn | None = None) -> None:
        self.api = api
        self._progress = progress or (lambda _msg: None)

    def _log(self, msg: str) -> None:
        logger.info(msg)
        self._progress(msg)

    def scrape(
        self,
        *,
        geo_level: GeoLevel = GeoLevel.DISTRICT,
        include_abroad: bool = True,
        id_eleccion: int | None = None,
    ) -> ScrapeResult:
        result = ScrapeResult()

        # 1. process + election tree -------------------------------------
        result.proceso = self.api.proceso_activo()
        eleccion_id = id_eleccion or result.proceso.id_eleccion_principal
        if eleccion_id is None:
            raise OnpeError("could not determine idEleccion from active process")
        self._log(
            f"process #{result.proceso.id} '{result.proceso.nombre}' "
            f"(idEleccion={eleccion_id})"
        )
        result.elecciones = self._safe(
            "elecciones", lambda: self.api.elecciones(result.proceso.id), result, []
        )

        # 2. geo tree -----------------------------------------------------
        result.ubigeos = self._safe(
            "ubigeos", lambda: self.api.ubigeos_flat(eleccion_id), result, []
        )
        self._log(f"loaded {len(result.ubigeos)} ubigeos")

        # 3. national + ambito scopes (totals AND participants) ----------
        self._collect_summary_scopes(eleccion_id, include_abroad, result)

        # 4. geographic totals sweep -------------------------------------
        if geo_level >= GeoLevel.DEPARTMENT:
            self._collect_geo_scopes(eleccion_id, geo_level, result.ubigeos, result)

        self._log(
            f"done: {len(result.scopes)} scopes, {len(result.errors)} errors"
        )
        return result

    # -- summary scopes ---------------------------------------------------

    def _collect_summary_scopes(
        self, eleccion_id: int, include_abroad: bool, result: ScrapeResult
    ) -> None:
        # National.
        scope = ScopeResult(tipo_filtro=TipoFiltro.ELECCION.value, nivel=0, nombre="NACIONAL")
        scope.totales = self._safe(
            "totales/national",
            lambda: self.api.totales(eleccion_id, TipoFiltro.ELECCION),
            result,
            None,
        )
        scope.participantes = self._safe(
            "participantes/national",
            lambda: self.api.participantes(eleccion_id, TipoFiltro.ELECCION),
            result,
            [],
        )
        result.scopes.append(scope)
        self._log("national scope collected")

        # Peru vs. abroad.
        ambitos: Iterable[AmbitoGeografico] = (
            (AmbitoGeografico.PERU, AmbitoGeografico.EXTRANJERO)
            if include_abroad
            else (AmbitoGeografico.PERU,)
        )
        for ambito in ambitos:
            sc = ScopeResult(
                tipo_filtro=TipoFiltro.AMBITO.value,
                ambito=int(ambito),
                nivel=0,
                nombre=ambito.name,
            )
            sc.totales = self._safe(
                f"totales/ambito={ambito.name}",
                lambda a=ambito: self.api.totales(
                    eleccion_id, TipoFiltro.AMBITO, ambito=a
                ),
                result,
                None,
            )
            sc.participantes = self._safe(
                f"participantes/ambito={ambito.name}",
                lambda a=ambito: self.api.participantes(
                    eleccion_id, TipoFiltro.AMBITO, ambito=a
                ),
                result,
                [],
            )
            result.scopes.append(sc)
        self._log("ambito scopes collected")

    # -- geographic sweep -------------------------------------------------

    def _collect_geo_scopes(
        self,
        eleccion_id: int,
        geo_level: GeoLevel,
        ubigeos: list[Ubigeo],
        result: ScrapeResult,
    ) -> None:
        level_filter = {
            1: TipoFiltro.NIVEL_01,
            2: TipoFiltro.NIVEL_02,
            3: TipoFiltro.NIVEL_03,
        }
        # ``dep-prov-distritos`` only lists district leaves, so expand them into
        # the department/province parents (with names from the ``DEP \ PROV \
        # DIST`` path) and keep only the levels up to the requested depth.
        #
        # Abroad continents (ambito=2, nivel 1) are skipped: they are a redundant
        # mid-level — the EXTRANJERO ambito row already totals all abroad voting,
        # and per-country (nivel 2) gives the useful breakdown. So abroad starts
        # at the country level, which lines up with Peru's province level.
        targets = [
            u
            for u in _expand_levels(ubigeos)
            if u.nivel <= int(geo_level)
            and not (_ambito_of(u.codigo) is AmbitoGeografico.EXTRANJERO and u.nivel == 1)
        ]
        total = len(targets)
        self._log(f"sweeping totals for {total} geographic units up to {geo_level.name}")

        for i, u in enumerate(targets, 1):
            tipo = level_filter[u.nivel]
            # Abroad units (continent/country/city, codes >= 900000) must be
            # queried under the EXTRANJERO ambito; Peru units under PERU. Using
            # the wrong ambito returns 204 (which is why abroad was skipped before
            # this was made per-unit).
            ambito = _ambito_of(u.codigo)
            sc = ScopeResult(
                tipo_filtro=tipo.value,
                ambito=int(ambito),
                ubigeo=u.codigo,
                nombre=u.ruta or u.nombre,
                nivel=u.nivel,
            )
            sc.totales = self._safe(
                f"totales/{u.codigo}",
                lambda u=u, tipo=tipo, ambito=ambito: self.api.totales(
                    eleccion_id,
                    tipo,
                    ambito=ambito,
                    id_ubigeo_departamento=int(u.departamento_codigo),
                    id_ubigeo_provincia=(
                        int(u.provincia_codigo) if u.nivel >= 2 else None
                    ),
                    id_ubigeo_distrito=(u.id_numerico if u.nivel >= 3 else None),
                ),
                result,
                None,
            )
            # Any unit without data for its ambito answers 204 -> None; skip it
            # rather than emit an empty row.
            if sc.totales is not None:
                result.scopes.append(sc)
            if i % 100 == 0 or i == total:
                self._log(f"  geo sweep {i}/{total}")

    # -- error isolation --------------------------------------------------

    def _safe(self, label: str, fn: Callable[[], object], result: ScrapeResult, fallback):
        try:
            return fn()
        except OnpeError as exc:
            msg = f"{label}: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            return fallback


def _ambito_of(codigo: str) -> AmbitoGeografico:
    """Abroad UBIGEOs are coded from 900000 up (continents 91-95)."""
    return (
        AmbitoGeografico.EXTRANJERO if codigo >= "900000" else AmbitoGeografico.PERU
    )


def _expand_levels(ubigeos: list[Ubigeo]) -> list[Ubigeo]:
    """Expand the flat district list into all hierarchy levels.

    The ``dep-prov-distritos`` endpoint returns only 6-digit district leaves with
    a ``DEPARTMENT \\ PROVINCE \\ DISTRICT`` path. This reconstructs the unique
    department (``..0000``) and province (``....00``) parents, naming each from
    the corresponding segment of a child's path, and returns departments first,
    then provinces, then districts (so a sweep visits coarse-to-fine).
    """
    departments: dict[str, Ubigeo] = {}
    provinces: dict[str, Ubigeo] = {}
    districts: list[Ubigeo] = []

    for u in ubigeos:
        if u.codigo == "000000":
            continue
        segments = [s.strip() for s in (u.ruta or "").split("\\")]
        dep_code, prov_code = u.departamento_codigo, u.provincia_codigo
        if dep_code not in departments:
            departments[dep_code] = Ubigeo(
                codigo=dep_code,
                nombre=segments[0] if segments else dep_code,
                nivel=1,
                ruta=segments[0] if segments else None,
            )
        if prov_code not in provinces:
            provinces[prov_code] = Ubigeo(
                codigo=prov_code,
                nombre=segments[1] if len(segments) > 1 else prov_code,
                nivel=2,
                ruta=" \\ ".join(segments[:2]) if len(segments) > 1 else None,
            )
        districts.append(u)

    return [*departments.values(), *provinces.values(), *districts]
