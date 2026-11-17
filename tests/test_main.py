"""Pruebas del arranque de la API (app/main.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_salud_responde():
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok"}


def test_sin_base_de_datos_la_app_sigue_arriba_y_avisa_claro():
    # RNF-10: si la base está dormida o sin configurar, no se cae ni muestra errores internos.
    from sqlalchemy.exc import OperationalError

    from app.db import BaseNoDisponible, obtener_db

    datos = {"correo": "nadie@umanizales.edu.co", "contrasena": "clave-segura-1"}
    for error in (
        BaseNoDisponible("Falta la variable DATABASE_URL."),
        OperationalError("select 1", {}, Exception("x")),
    ):

        def sin_base(error=error):
            raise error

        app.dependency_overrides[obtener_db] = sin_base
        try:
            r = cliente.post("/api/sesion", json=datos)
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 503
        assert "DATABASE_URL" not in r.text
        assert "select" not in r.text
    assert cliente.get("/salud").status_code == 200


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_la_documentacion_de_la_api_no_queda_publica(ruta):
    # D-10 (OWASP A02): nadie sin sesión puede ver la lista de rutas.
    assert cliente.get(ruta).status_code == 404
