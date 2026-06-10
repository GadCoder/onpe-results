"""Typed domain models for the ONPE results API.

Each class mirrors one JSON payload the API returns, with snake_case fields and a
``from_api`` classmethod that tolerates the API's occasional missing/null keys.
Keeping parsing here (rather than scattered through the orchestrator) means the
shape of the upstream data is documented in exactly one place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AmbitoGeografico(int, Enum):
    """``idAmbitoGeografico`` values (from the SPA: ``dn=1``, ``Hr=2``)."""

    PERU = 1
    EXTRANJERO = 2


class TipoFiltro(str, Enum):
    """``tipoFiltro`` values the summary endpoints accept."""

    ELECCION = "eleccion"  # national aggregate
    AMBITO = "ambito_geografico"  # Peru vs. abroad
    NIVEL_01 = "ubigeo_nivel_01"  # department
    NIVEL_02 = "ubigeo_nivel_02"  # province
    NIVEL_03 = "ubigeo_nivel_03"  # district


def _f(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present key from ``d`` (handles API field aliases)."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


@dataclass(slots=True)
class Proceso:
    """An electoral process (e.g. the 2026 second round)."""

    id: int
    nombre: str
    acronimo: str | None = None
    id_eleccion_principal: int | None = None
    tipo_proceso_electoral: str | None = None
    fecha_proceso: int | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Proceso:
        return cls(
            id=d["id"],
            nombre=_f(d, "nombre", default=""),
            acronimo=_f(d, "acronimo"),
            id_eleccion_principal=_f(d, "idEleccionPrincipal"),
            tipo_proceso_electoral=_f(d, "tipoProcesoElectoral"),
            fecha_proceso=_f(d, "fechaProceso"),
        )


@dataclass(slots=True)
class Eleccion:
    """A node in the election/menu tree returned by ``proceso/{id}/elecciones``."""

    id: int
    nombre: str
    id_eleccion: int | None = None
    padre: int | None = None
    tiene_hijos: bool = False
    url: str | None = None
    es_principal: bool = False

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Eleccion:
        return cls(
            id=d["id"],
            nombre=_f(d, "nombre", default=""),
            id_eleccion=_f(d, "idEleccion"),
            padre=_f(d, "padre"),
            tiene_hijos=bool(_f(d, "hijos", default=False)),
            url=_f(d, "url"),
            es_principal=bool(_f(d, "esPrincipal", default=False)),
        )


@dataclass(slots=True)
class Ubigeo:
    """A geographic unit. ``codigo`` is the 6-digit UBIGEO; ``nombre`` is the
    leaf name; ``ruta`` is the full ``DEPARTMENT \\ PROVINCE \\ DISTRICT`` path
    when available (from the flat ``dep-prov-distritos`` listing)."""

    codigo: str
    nombre: str
    nivel: int  # 1=department, 2=province, 3=district
    ruta: str | None = None

    @property
    def departamento_codigo(self) -> str:
        return self.codigo[:2] + "0000"

    @property
    def provincia_codigo(self) -> str:
        return self.codigo[:4] + "00"

    @property
    def id_numerico(self) -> int:
        """Numeric form the cascade endpoints want (``010000`` -> ``10000``)."""
        return int(self.codigo)


@dataclass(slots=True)
class Totales:
    """Processing + turnout + vote totals for one geographic scope."""

    actas_contabilizadas_pct: float | None = None
    actas_contabilizadas: int | None = None
    total_actas: int | None = None
    participacion_ciudadana_pct: float | None = None
    actas_enviadas_jee_pct: float | None = None
    actas_enviadas_jee: int | None = None
    actas_pendientes_jee_pct: float | None = None
    actas_pendientes_jee: int | None = None
    total_votos_emitidos: int | None = None
    total_votos_validos: int | None = None
    porcentaje_votos_emitidos: float | None = None
    porcentaje_votos_validos: float | None = None
    fecha_actualizacion: int | None = None
    id_ubigeo_departamento: int | None = None
    id_ubigeo_provincia: int | None = None
    id_ubigeo_distrito: int | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Totales:
        return cls(
            actas_contabilizadas_pct=_f(d, "actasContabilizadas"),
            actas_contabilizadas=_f(d, "contabilizadas"),
            total_actas=_f(d, "totalActas"),
            participacion_ciudadana_pct=_f(d, "participacionCiudadana"),
            actas_enviadas_jee_pct=_f(d, "actasEnviadasJee"),
            actas_enviadas_jee=_f(d, "enviadasJee"),
            actas_pendientes_jee_pct=_f(d, "actasPendientesJee"),
            actas_pendientes_jee=_f(d, "pendientesJee"),
            total_votos_emitidos=_f(d, "totalVotosEmitidos"),
            total_votos_validos=_f(d, "totalVotosValidos"),
            porcentaje_votos_emitidos=_f(d, "porcentajeVotosEmitidos"),
            porcentaje_votos_validos=_f(d, "porcentajeVotosValidos"),
            fecha_actualizacion=_f(d, "fechaActualizacion"),
            id_ubigeo_departamento=_f(d, "idUbigeoDepartamento"),
            id_ubigeo_provincia=_f(d, "idUbigeoProvincia"),
            id_ubigeo_distrito=_f(d, "idUbigeoDistrito"),
        )


@dataclass(slots=True)
class Participante:
    """A candidate / political organisation result line."""

    nombre_agrupacion_politica: str
    codigo_agrupacion_politica: int | None
    nombre_candidato: str | None
    dni_candidato: str | None
    total_votos_validos: int | None
    porcentaje_votos_validos: float | None
    porcentaje_votos_emitidos: float | None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Participante:
        return cls(
            nombre_agrupacion_politica=_f(d, "nombreAgrupacionPolitica", default=""),
            codigo_agrupacion_politica=_f(d, "codigoAgrupacionPolitica"),
            nombre_candidato=_f(d, "nombreCandidato"),
            dni_candidato=_f(d, "dniCandidato"),
            total_votos_validos=_f(d, "totalVotosValidos"),
            porcentaje_votos_validos=_f(d, "porcentajeVotosValidos"),
            porcentaje_votos_emitidos=_f(d, "porcentajeVotosEmitidos"),
        )


@dataclass(slots=True)
class ScopeResult:
    """Totals (+ optional participants) bound to a geographic scope.

    This is the unit the scraper emits: one per (tipo_filtro, ubigeo) it visits.
    """

    tipo_filtro: str
    ambito: int | None = None
    ubigeo: str | None = None
    nombre: str | None = None
    nivel: int = 0  # 0=national, 1=dept, 2=prov, 3=dist
    totales: Totales | None = None
    participantes: list[Participante] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "tipo_filtro": self.tipo_filtro,
            "ambito": self.ambito,
            "ubigeo": self.ubigeo,
            "nombre": self.nombre,
            "nivel": self.nivel,
        }
        if self.totales is not None:
            rec.update({f"tot_{k}": v for k, v in asdict(self.totales).items()})
        return rec
