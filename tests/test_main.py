"""Pruebas del arranque de la API (app/main.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_salud_responde():
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok"}


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_la_documentacion_de_la_api_no_queda_publica(ruta):
    # D-10 (OWASP A02): nadie sin sesión puede ver la lista de rutas.
    assert cliente.get(ruta).status_code == 404
