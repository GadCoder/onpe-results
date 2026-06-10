"""Typed endpoint methods for the ONPE results API.

Every method here corresponds to a request the official Angular SPA makes,
verified by replaying it with a Chrome-impersonated client. Endpoints are
grouped the way the frontend groups them (proceso / ubigeos / resumen-general /
actas).

Endpoint reference (all under ``/presentacion-backend``)::

    GET  proceso/proceso-electoral-activo
    GET  proceso/{idProceso}/elecciones
    GET  ubigeos/dep-prov-distritos          ?idEleccion
    GET  ubigeos/departamentos               ?idEleccion&idAmbitoGeografico
    GET  ubigeos/provincias                  ?idEleccion&idAmbitoGeografico&idUbigeoDepartamento
    GET  ubigeos/distritos                    ?idEleccion&idAmbitoGeografico&idUbigeoProvincia
    GET  resumen-general/totales              ?idEleccion&tipoFiltro[&idAmbitoGeografico&ubigeoNivel1..3]
    GET  resumen-general/participantes        ?idEleccion&tipoFiltro[&idAmbitoGeografico]
    POST actas/buscar/mesa                    {codigoMesa}
    POST actas/locales                        {idEleccion, idUbigeo}

Note: ``resumen-general/participantes`` only serves the national (``eleccion``)
and ``ambito_geografico`` scopes for this process; geographic levels return 500
upstream, so the orchestrator does not request them.
"""

from __future__ import annotations

from typing import Any

from .http import OnpeClient
from .models import (
    AmbitoGeografico,
    Eleccion,
    Participante,
    Proceso,
    TipoFiltro,
    Totales,
    Ubigeo,
)


class OnpeApi:
    """Thin, typed wrapper over :class:`OnpeClient`."""

    def __init__(self, client: OnpeClient) -> None:
        self.client = client

    # -- proceso ----------------------------------------------------------

    def proceso_activo(self) -> Proceso:
        """The currently active electoral process."""
        return Proceso.from_api(self.client.get("proceso/proceso-electoral-activo"))

    def elecciones(self, id_proceso: int) -> list[Eleccion]:
        """The election/menu tree for a process (Resumen, Presidencial, ...)."""
        data = self.client.get(f"proceso/{id_proceso}/elecciones") or []
        return [Eleccion.from_api(d) for d in data]

    # -- ubigeos ----------------------------------------------------------

    def ubigeos_flat(self, id_eleccion: int) -> list[Ubigeo]:
        """Every UBIGEO in one flat list, with full ``DEP \\ PROV \\ DIST`` paths.

        This single call is enough to reconstruct the whole hierarchy, so it is
        the orchestrator's preferred source of the geo tree.
        """
        data = self.client.get(
            "ubigeos/dep-prov-distritos", {"idEleccion": id_eleccion}
        )
        out: list[Ubigeo] = []
        for d in data or []:
            codigo = d["ubigeo"]
            ruta = d.get("nombre", "")
            leaf = ruta.split("\\")[-1].strip() if ruta else codigo
            out.append(
                Ubigeo(codigo=codigo, nombre=leaf, nivel=_nivel_of(codigo), ruta=ruta)
            )
        return out

    def departamentos(
        self, id_eleccion: int, ambito: AmbitoGeografico = AmbitoGeografico.PERU
    ) -> list[Ubigeo]:
        data = self.client.get(
            "ubigeos/departamentos",
            {"idEleccion": id_eleccion, "idAmbitoGeografico": int(ambito)},
        )
        return [_ubigeo(d, 1) for d in data or []]

    def provincias(
        self,
        id_eleccion: int,
        id_ubigeo_departamento: int,
        ambito: AmbitoGeografico = AmbitoGeografico.PERU,
    ) -> list[Ubigeo]:
        data = self.client.get(
            "ubigeos/provincias",
            {
                "idEleccion": id_eleccion,
                "idAmbitoGeografico": int(ambito),
                "idUbigeoDepartamento": id_ubigeo_departamento,
            },
        )
        return [_ubigeo(d, 2) for d in data or []]

    def distritos(
        self,
        id_eleccion: int,
        id_ubigeo_provincia: int,
        ambito: AmbitoGeografico = AmbitoGeografico.PERU,
    ) -> list[Ubigeo]:
        data = self.client.get(
            "ubigeos/distritos",
            {
                "idEleccion": id_eleccion,
                "idAmbitoGeografico": int(ambito),
                "idUbigeoProvincia": id_ubigeo_provincia,
            },
        )
        return [_ubigeo(d, 3) for d in data or []]

    # -- resumen general --------------------------------------------------

    def totales(
        self,
        id_eleccion: int,
        tipo_filtro: TipoFiltro = TipoFiltro.ELECCION,
        *,
        ambito: AmbitoGeografico | None = None,
        id_ubigeo_departamento: int | None = None,
        id_ubigeo_provincia: int | None = None,
        id_ubigeo_distrito: int | None = None,
    ) -> Totales | None:
        """Processing/turnout/vote totals for a scope.

        ``tipo_filtro`` selects the aggregation level. For geographic levels pass
        the *numeric* UBIGEO ids for the levels at and above the target — e.g. a
        district needs all three. (The codes are the 6-digit UBIGEO read as an
        int: ``"010200"`` -> ``10200``. Passing them as ``ubigeoNivelN`` strings
        is silently ignored by the backend, which is why these are explicit
        numeric ids.)
        """
        params: dict[str, Any] = {
            "idEleccion": id_eleccion,
            "tipoFiltro": tipo_filtro.value,
        }
        if ambito is not None:
            params["idAmbitoGeografico"] = int(ambito)
        if id_ubigeo_departamento is not None:
            params["idUbigeoDepartamento"] = id_ubigeo_departamento
        if id_ubigeo_provincia is not None:
            params["idUbigeoProvincia"] = id_ubigeo_provincia
        if id_ubigeo_distrito is not None:
            params["idUbigeoDistrito"] = id_ubigeo_distrito
        data = self.client.get("resumen-general/totales", params)
        return Totales.from_api(data) if data else None

    def participantes(
        self,
        id_eleccion: int,
        tipo_filtro: TipoFiltro = TipoFiltro.ELECCION,
        *,
        ambito: AmbitoGeografico | None = None,
    ) -> list[Participante]:
        """Candidate / organisation vote results (national or by ambito only)."""
        params: dict[str, Any] = {
            "idEleccion": id_eleccion,
            "tipoFiltro": tipo_filtro.value,
        }
        if ambito is not None:
            params["idAmbitoGeografico"] = int(ambito)
        data = self.client.get("resumen-general/participantes", params)
        return [Participante.from_api(d) for d in data or []]

    # -- actas ------------------------------------------------------------

    def buscar_mesa(self, codigo_mesa: str) -> Any:
        """Look up a single polling-station tally sheet (acta) by its code."""
        return self.client.post("actas/buscar/mesa", {"codigoMesa": codigo_mesa})

    def locales(self, id_eleccion: int, id_ubigeo: int) -> Any:
        """List voting venues (locales) within a UBIGEO."""
        return self.client.post(
            "actas/locales", {"idEleccion": id_eleccion, "idUbigeo": id_ubigeo}
        )


def _nivel_of(codigo: str) -> int:
    """Infer hierarchy level from a 6-digit UBIGEO's zero padding."""
    if codigo[2:] == "0000":
        return 1
    if codigo[4:] == "00":
        return 2
    return 3


def _ubigeo(d: dict[str, Any], nivel: int) -> Ubigeo:
    return Ubigeo(codigo=d["ubigeo"], nombre=d.get("nombre", ""), nivel=nivel)
