from __future__ import annotations

from .models import RouteConfig

BASE_URL = "https://resultadoelectoral.onpe.gob.pe"
API_BASE = f"{BASE_URL}/presentacion-backend"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

ROUTES: list[RouteConfig] = [
    RouteConfig(
        key="presidenciales",
        page_url="https://resultadoelectoral.onpe.gob.pe/main/presidenciales",
        election_id=10,
        mode="ambito_geografico",
        participants_path="/eleccion-presidencial/participantes-ubicacion-geografica-nombre",
    ),
    RouteConfig(
        key="senadores_distrito_nacional_unico",
        page_url="https://resultadoelectoral.onpe.gob.pe/main/senadores-distrito-nacional-unico",
        election_id=15,
        mode="ambito_geografico",
        participants_path="/senadores-distrito-unico/participantes-ubicacion-geografica-nombre",
    ),
    RouteConfig(
        key="senadores_distrito_electoral_multiple",
        page_url="https://resultadoelectoral.onpe.gob.pe/main/senadores-distrito-electoral-multiple",
        election_id=14,
        mode="distrito_electoral",
        participants_path="/senadores-distrital-multiple/participantes-ubicacion-geografica",
    ),
    RouteConfig(
        key="diputados",
        page_url="https://resultadoelectoral.onpe.gob.pe/main/diputados",
        election_id=13,
        mode="distrito_electoral",
        participants_path="/eleccion-diputado/participantes-ubicacion-geografica-nombre",
    ),
    RouteConfig(
        key="parlamento_andino",
        page_url="https://resultadoelectoral.onpe.gob.pe/main/parlamento-andino",
        election_id=12,
        mode="ambito_geografico",
        participants_path="/parlamento-andino/participantes-ubicacion-geografica-nombre",
    ),
]
