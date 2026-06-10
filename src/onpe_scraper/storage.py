"""Persistence for scrape outputs.

Writes both machine-friendly JSON (full fidelity) and flat CSVs (one row per
scope / per candidate) so results drop straight into a spreadsheet or BI tool.
All writes are atomic-ish (write then replace) and create the output dir on
demand.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from .models import ScopeResult


def _default(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"not JSON-serialisable: {type(obj)!r}")


class Storage:
    """Writes the various scrape artifacts under ``output_dir``."""

    def __init__(self, output_dir: Path) -> None:
        self.dir = output_dir
        self.raw = output_dir / "raw"

    def _ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: Any, *, raw: bool = False) -> Path:
        self._ensure()
        path = (self.raw if raw else self.dir) / name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_default),
            encoding="utf-8",
        )
        return path

    def write_csv(self, name: str, rows: Sequence[dict[str, Any]]) -> Path | None:
        if not rows:
            return None
        self._ensure()
        path = self.dir / name
        # Union of keys keeps the header stable even if some rows omit fields.
        fields: list[str] = []
        for row in rows:
            for k in row:
                if k not in fields:
                    fields.append(k)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    # -- high-level: persist a finished scrape ----------------------------

    def write_scopes(self, scopes: Sequence[ScopeResult]) -> dict[str, Path | None]:
        """Persist scope results as totals CSV + participants CSV + full JSON."""
        totals_rows = [s.to_record() for s in scopes]

        part_rows: list[dict[str, Any]] = []
        for s in scopes:
            for p in s.participantes:
                part_rows.append(
                    {
                        "tipo_filtro": s.tipo_filtro,
                        "ambito": s.ambito,
                        "ubigeo": s.ubigeo,
                        "nombre_ambito": s.nombre,
                        **asdict(p),
                    }
                )

        return {
            "totales_csv": self.write_csv("totales.csv", totals_rows),
            "participantes_csv": self.write_csv("participantes.csv", part_rows),
            "scopes_json": self.write_json("scopes.json", [asdict(s) for s in scopes]),
        }
