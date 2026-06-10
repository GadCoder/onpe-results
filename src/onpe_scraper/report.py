"""National + geographic result snapshots, history, and notification reports.

This builds the data needed to send an update message like::

    📬 Nuevos resultados ONPE
    🕒 Actualización: 19:22:00 09/06/2026
    📊 Actas contabilizadas: 96.412%
    🟥 Keiko Fujimori — 8.908.141 (49.884%)
    🟦 Roberto Sánchez — 8.949.555 (50.116%)
    🏆 Va ganando: Roberto Sánchez ...
    🔁 Comparación con el resultado anterior: ...
    📍 Avance de actas procesadas (variación): departamentos / provincias / países

A :class:`Snapshot` is the national totals + per-candidate vote line **and** the
per-geographic-unit actas-processed counts at one ``fechaActualizacion``.
Snapshots are appended to a JSONL history file; each report compares the current
snapshot against the most recent *earlier* one to produce the deltas — both the
national race (votes, percentage points, lead change) and the change in actas
processed per department, province and foreign country.

For the geographic section only units **that changed** are reported, each list
ordered by the size of the variation. The output is a single JSON object
carrying the structured fields and a ready-to-send ``mensaje`` string.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .api import OnpeApi
from .config import CANDIDATE_DISPLAY, FALLBACK_EMOJI, REPORT_TZ
from .models import TipoFiltro
from .scraper import GeoLevel, OnpeScraper, ScrapeResult

#: How many geo rows per group to render in the text message (JSON keeps all).
DEFAULT_TOP_GEO = 10


@dataclass(slots=True)
class CandidateSnapshot:
    codigo: int
    agrupacion: str
    nombre_api: str
    votos_validos: int
    porcentaje_validos: float

    def display_name(self) -> str:
        cfg = CANDIDATE_DISPLAY.get(self.codigo)
        return cfg["nombre"] if cfg else self.nombre_api.title()

    def emoji(self) -> str:
        cfg = CANDIDATE_DISPLAY.get(self.codigo)
        return cfg["emoji"] if cfg else FALLBACK_EMOJI


@dataclass(slots=True)
class GeoActas:
    """Actas-processed counts for one geographic unit at one timestamp."""

    tipo: str  # "departamento" | "provincia" | "pais"
    ambito: int
    ubigeo: str
    nombre: str
    actas_contabilizadas: int
    total_actas: int
    actas_contabilizadas_pct: float


@dataclass(slots=True)
class Snapshot:
    """National results + per-geo actas at a single update timestamp."""

    timestamp: int  # epoch ms (fechaActualizacion)
    actas_contabilizadas_pct: float
    candidates: list[CandidateSnapshot]
    geo: list[GeoActas] = field(default_factory=list)

    def candidate(self, codigo: int) -> CandidateSnapshot | None:
        return next((c for c in self.candidates if c.codigo == codigo), None)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "actas_contabilizadas_pct": self.actas_contabilizadas_pct,
            "candidates": [asdict(c) for c in self.candidates],
            "geo": [asdict(g) for g in self.geo],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            timestamp=d["timestamp"],
            actas_contabilizadas_pct=d["actas_contabilizadas_pct"],
            candidates=[CandidateSnapshot(**c) for c in d["candidates"]],
            geo=[GeoActas(**g) for g in d.get("geo", [])],
        )

    @classmethod
    def from_scrape(cls, result: ScrapeResult) -> "Snapshot":
        """Build a snapshot from a province-level :class:`ScrapeResult`.

        Pulls the national race from the ``eleccion`` scope and the actas counts
        from each department (Peru nivel 1), province (Peru nivel 2) and foreign
        country (abroad nivel 2). Abroad continents are not swept, so they never
        appear here.
        """
        national = next(
            (s for s in result.scopes if s.tipo_filtro == TipoFiltro.ELECCION.value),
            None,
        )
        if national is None or national.totales is None:
            raise RuntimeError("national totales returned no data")

        candidates = [
            CandidateSnapshot(
                codigo=p.codigo_agrupacion_politica,
                agrupacion=p.nombre_agrupacion_politica,
                nombre_api=p.nombre_candidato or p.nombre_agrupacion_politica,
                votos_validos=p.total_votos_validos or 0,
                porcentaje_validos=p.porcentaje_votos_validos or 0.0,
            )
            for p in sorted(
                national.participantes, key=lambda p: p.codigo_agrupacion_politica or 0
            )
        ]

        geo: list[GeoActas] = []
        for s in result.scopes:
            if s.nivel not in (1, 2) or s.totales is None or s.ubigeo is None:
                continue
            geo.append(
                GeoActas(
                    tipo=_geo_tipo(s.ambito or 1, s.nivel),
                    ambito=s.ambito or 1,
                    ubigeo=s.ubigeo,
                    nombre=s.nombre or s.ubigeo,
                    actas_contabilizadas=s.totales.actas_contabilizadas or 0,
                    total_actas=s.totales.total_actas or 0,
                    actas_contabilizadas_pct=s.totales.actas_contabilizadas_pct or 0.0,
                )
            )

        return cls(
            timestamp=national.totales.fecha_actualizacion or 0,
            actas_contabilizadas_pct=national.totales.actas_contabilizadas_pct or 0.0,
            candidates=candidates,
            geo=geo,
        )


def _geo_tipo(ambito: int, nivel: int) -> str:
    if ambito == 2:
        return "pais"
    return "departamento" if nivel == 1 else "provincia"


def fetch_snapshot(
    api: OnpeApi,
    id_eleccion: int,
    *,
    with_geo: bool = True,
    progress=None,
) -> Snapshot:
    """Capture the current results.

    With ``with_geo`` (default) it runs a province-level sweep so the snapshot
    includes per-department/province/country actas. Without it, only the national
    race is fetched (one request)."""
    if with_geo:
        scraper = OnpeScraper(api, progress=progress)
        result = scraper.scrape(
            geo_level=GeoLevel.PROVINCE, include_abroad=True, id_eleccion=id_eleccion
        )
        return Snapshot.from_scrape(result)

    totales = api.totales(id_eleccion, TipoFiltro.ELECCION)
    participantes = api.participantes(id_eleccion, TipoFiltro.ELECCION)
    if totales is None:
        raise RuntimeError("national totales returned no data")
    candidates = [
        CandidateSnapshot(
            codigo=p.codigo_agrupacion_politica,
            agrupacion=p.nombre_agrupacion_politica,
            nombre_api=p.nombre_candidato or p.nombre_agrupacion_politica,
            votos_validos=p.total_votos_validos or 0,
            porcentaje_validos=p.porcentaje_votos_validos or 0.0,
        )
        for p in sorted(participantes, key=lambda p: p.codigo_agrupacion_politica or 0)
    ]
    return Snapshot(
        timestamp=totales.fecha_actualizacion or 0,
        actas_contabilizadas_pct=totales.actas_contabilizadas_pct or 0.0,
        candidates=candidates,
    )


# -- history (JSONL, one snapshot per line) -------------------------------


class History:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Snapshot]:
        if not self.path.exists():
            return []
        snaps = [
            Snapshot.from_dict(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return sorted(snaps, key=lambda s: s.timestamp)

    def previous_to(self, timestamp: int) -> Snapshot | None:
        """Most recent stored snapshot strictly older than ``timestamp``."""
        earlier = [s for s in self.load() if s.timestamp < timestamp]
        return earlier[-1] if earlier else None

    def append(self, snap: Snapshot) -> bool:
        """Append a snapshot unless its timestamp is already recorded.

        Returns True if it was written (i.e. genuinely new data)."""
        if any(s.timestamp == snap.timestamp for s in self.load()):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap.to_dict(), ensure_ascii=False) + "\n")
        return True


# -- report building ------------------------------------------------------


def _fmt_ts(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo(REPORT_TZ)).strftime(
        "%H:%M:%S %d/%m/%Y"
    )


def build_report(
    current: Snapshot,
    previous: Snapshot | None,
    *,
    top_geo: int = DEFAULT_TOP_GEO,
) -> dict:
    """Assemble the structured report dict (+ rendered ``mensaje``)."""
    ordered = current.candidates
    ranked = sorted(ordered, key=lambda c: c.porcentaje_validos, reverse=True)
    leader, runner = ranked[0], ranked[1]
    dif_votos = leader.votos_validos - runner.votos_validos
    dif_pp = round(leader.porcentaje_validos - runner.porcentaje_validos, 3)

    report: dict = {
        "timestamp": current.timestamp,
        "timestamp_display": _fmt_ts(current.timestamp),
        "actas_contabilizadas_pct": current.actas_contabilizadas_pct,
        "candidatos": [
            {
                "codigo": c.codigo,
                "agrupacion": c.agrupacion,
                "nombre": c.display_name(),
                "emoji": c.emoji(),
                "votos_validos": c.votos_validos,
                "porcentaje_validos": c.porcentaje_validos,
            }
            for c in ordered
        ],
        "va_ganando": {"codigo": leader.codigo, "nombre": leader.display_name()},
        "diferencia": {"votos": dif_votos, "puntos_pct": dif_pp},
        "comparacion": _build_comparison(current, previous, leader, runner),
    }
    report["mensaje"] = render_message(report, top_geo=top_geo)
    report["mensajes"] = {
        "general": render_general(report),
        "departamentos": _render_geo_file(
            report,
            "Actas procesadas — Departamentos y provincias",
            [("departamentos", "🏛 Departamentos:"), ("provincias", "🗺 Provincias:")],
            top_geo,
        ),
        "paises": _render_geo_file(
            report,
            "Actas procesadas — Países (extranjero)",
            [("paises", "🌎 Países:")],
            top_geo,
        ),
    }
    return report


def _build_comparison(
    current: Snapshot,
    previous: Snapshot | None,
    leader: CandidateSnapshot,
    runner: CandidateSnapshot,
) -> dict | None:
    if previous is None:
        return None

    cand_deltas = []
    for c in current.candidates:
        prev = previous.candidate(c.codigo)
        if prev is None:
            continue
        cand_deltas.append(
            {
                "codigo": c.codigo,
                "nombre": c.display_name(),
                "delta_votos": c.votos_validos - prev.votos_validos,
                "delta_pp": round(c.porcentaje_validos - prev.porcentaje_validos, 3),
            }
        )

    # Lead change measured for the *current* leader vs the same runner-up.
    pl, pr = previous.candidate(leader.codigo), previous.candidate(runner.codigo)
    ventaja_delta = None
    if pl and pr:
        prev_lead_votos = pl.votos_validos - pr.votos_validos
        prev_lead_pp = pl.porcentaje_validos - pr.porcentaje_validos
        cur_lead_votos = leader.votos_validos - runner.votos_validos
        cur_lead_pp = leader.porcentaje_validos - runner.porcentaje_validos
        ventaja_delta = {
            "votos": cur_lead_votos - prev_lead_votos,
            "puntos_pct": round(cur_lead_pp - prev_lead_pp, 3),
        }

    return {
        "previo_timestamp": previous.timestamp,
        "previo_display": _fmt_ts(previous.timestamp),
        "actas_contabilizadas_pp": round(
            current.actas_contabilizadas_pct - previous.actas_contabilizadas_pct, 3
        ),
        "candidatos": cand_deltas,
        "ventaja": ventaja_delta,
        "geografico": _geo_comparison(current, previous),
    }


def _geo_comparison(current: Snapshot, previous: Snapshot) -> dict:
    """Per-unit change in actas processed, only changed units, sorted by
    variation. Grouped into departamentos / provincias / paises."""
    prev_by_code = {g.ubigeo: g for g in previous.geo}
    bucket = {"departamento": "departamentos", "provincia": "provincias", "pais": "paises"}
    groups: dict[str, list[dict]] = {"departamentos": [], "provincias": [], "paises": []}

    for g in current.geo:
        p = prev_by_code.get(g.ubigeo)
        if p is None:
            continue
        delta_actas = g.actas_contabilizadas - p.actas_contabilizadas
        if delta_actas == 0:  # only units where actas processed changed
            continue
        groups[bucket[g.tipo]].append(
            {
                "ubigeo": g.ubigeo,
                "nombre": g.nombre,
                "actas_previo": p.actas_contabilizadas,
                "actas_actual": g.actas_contabilizadas,
                "total_actas": g.total_actas,
                "delta_actas": delta_actas,
                "pct_previo": p.actas_contabilizadas_pct,
                "pct_actual": g.actas_contabilizadas_pct,
                "delta_pp": round(
                    g.actas_contabilizadas_pct - p.actas_contabilizadas_pct, 3
                ),
            }
        )

    for rows in groups.values():
        rows.sort(key=lambda x: abs(x["delta_actas"]), reverse=True)
    return groups


# -- message rendering ----------------------------------------------------


def _votos(n: int) -> str:
    """8908141 -> '8.908.141' (Spanish thousands separator)."""
    return f"{n:,}".replace(",", ".")


def _svotos(n: int) -> str:
    return f"{'+' if n >= 0 else '-'}{_votos(abs(n))}"


def _render_geo_group(title: str, rows: list[dict], top: int) -> list[str]:
    if not rows:
        return []
    lines = [title]
    for r in rows[:top]:
        lines.append(
            f"  • {r['nombre']}: {r['pct_actual']:.3f}% procesado "
            f"({_votos(r['actas_actual'])}/{_votos(r['total_actas'])}) · "
            f"{_svotos(r['delta_actas'])} actas, {r['delta_pp']:+.3f} pp"
        )
    if len(rows) > top:
        lines.append(f"  … y {len(rows) - top} más")
    return lines


def render_general(report: dict) -> str:
    """The national-race message: turnout headline, candidates, leader and the
    national-level comparison. No geographic detail."""
    lines = [
        "📬 Nuevos resultados ONPE",
        f"🕒 Actualización: {report['timestamp_display']}",
        f"📊 Actas contabilizadas: {report['actas_contabilizadas_pct']:.3f}%",
        "",
    ]
    for c in report["candidatos"]:
        lines += [
            f"{c['emoji']} {c['nombre']}",
            f"* Votos válidos: {_votos(c['votos_validos'])}",
            f"* % válidos: {c['porcentaje_validos']:.3f}%",
            "",
        ]
    dif = report["diferencia"]
    lines += [
        f"🏆 Va ganando: {report['va_ganando']['nombre']}",
        f"📈 Diferencia actual: {_votos(dif['votos'])} votos ({dif['puntos_pct']:.3f} pp)",
    ]

    comp = report["comparacion"]
    if comp:
        lines += ["", "🔁 Comparación con el resultado anterior:"]
        lines.append(f"* Actas contabilizadas: {comp['actas_contabilizadas_pp']:+.3f} pp")
        for c in comp["candidatos"]:
            lines.append(
                f"* {c['nombre']}: {_svotos(c['delta_votos'])} votos / {c['delta_pp']:+.3f} pp"
            )
        if comp["ventaja"]:
            v = comp["ventaja"]
            lines.append(
                f"* Ventaja: {_svotos(v['votos'])} votos ({v['puntos_pct']:+.3f} pp)"
            )
    return "\n".join(lines)


def _render_geo_file(
    report: dict,
    title: str,
    groups: list[tuple[str, str]],
    top: int,
) -> str:
    """A standalone message for one or more geographic groups (each carries its
    own timestamp header so it can be sent on its own)."""
    lines = [
        f"📍 {title}",
        f"🕒 Actualización: {report['timestamp_display']}",
        "",
    ]
    comp = report["comparacion"]
    if not comp:
        lines.append("Sin resultado anterior para comparar.")
        return "\n".join(lines)

    geo = comp.get("geografico") or {}
    body: list[str] = []
    for key, subtitle in groups:
        body += _render_geo_group(subtitle, geo.get(key, []), top)
    if not body:
        body = ["Sin variación de actas procesadas vs. el resultado anterior."]
    return "\n".join(lines + body)


def render_message(report: dict, *, top_geo: int = DEFAULT_TOP_GEO) -> str:
    """The full combined message (national + geographic), kept for the
    ``report['mensaje']`` field and any single-message use."""
    lines = [render_general(report)]
    comp = report["comparacion"]
    if comp:
        geo = comp.get("geografico") or {}
        geo_lines: list[str] = []
        geo_lines += _render_geo_group("🏛 Departamentos:", geo.get("departamentos", []), top_geo)
        geo_lines += _render_geo_group("🗺 Provincias:", geo.get("provincias", []), top_geo)
        geo_lines += _render_geo_group("🌎 Países:", geo.get("paises", []), top_geo)
        if geo_lines:
            lines += ["", "📍 Avance de actas procesadas (variación):", *geo_lines]
    return "\n".join(lines)
