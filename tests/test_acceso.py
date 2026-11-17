"""Control de acceso por rol (OWASP A01, RNF-06). Fila C5 de la matriz del SRS.

La tabla de app/api/rutas.py manda: estas pruebas revisan que cada ruta que ya
existe en la app la cumpla, sin tener que escribir una prueba por ruta.
"""

import re
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount

from app.api.rutas import RUTAS
from app.esquemas import Rol
from app.main import app

TABLA = {(r.metodo, r.ruta): r for r in RUTAS}


def _rutas(contenedor):
    """Todas las rutas de la app. FastAPI guarda las de cada módulo dentro de un contenedor."""
    for ruta in contenedor.routes:
        if isinstance(ruta, Mount):
            continue
        if isinstance(ruta, APIRoute):
            yield ruta
        elif hasattr(ruta, "original_router"):
            yield from _rutas(ruta.original_router)
        else:  # si FastAPI cambia otra vez, que la prueba falle en vez de saltarse rutas
            raise AssertionError(f"Tipo de ruta desconocido: {type(ruta).__name__}")


CONSTRUIDAS = sorted((metodo, ruta.path) for ruta in _rutas(app) for metodo in ruta.methods)
ESPERADAS_EN_AUTH = {
    ("POST", "/api/sesion"),
    ("DELETE", "/api/sesion"),
    ("GET", "/api/yo"),
    ("PUT", "/api/yo/contrasena"),
    ("GET", "/api/usuarios"),
    ("POST", "/api/usuarios"),
    ("PATCH", "/api/usuarios/{usuario_id}"),
    ("POST", "/api/usuarios/{usuario_id}/clave-temporal"),
    ("GET", "/api/auditoria"),
}


ESPERADAS_EN_RUBRICAS = {
    ("GET", "/api/cohortes"),
    ("POST", "/api/cohortes"),
    ("GET", "/api/laboratorios"),
    ("POST", "/api/laboratorios"),
    ("GET", "/api/laboratorios/{laboratorio_id}"),
    ("PATCH", "/api/laboratorios/{laboratorio_id}"),
    ("GET", "/api/laboratorios/{laboratorio_id}/rubrica"),
    ("POST", "/api/laboratorios/{laboratorio_id}/rubrica"),
    ("PUT", "/api/laboratorios/{laboratorio_id}/rubrica"),
    ("GET", "/api/laboratorios/{laboratorio_id}/rubrica/versiones"),
}
ESPERADAS_EN_ENTREGAS = {
    ("POST", "/api/entregas"),
    ("GET", "/api/mis-entregas"),
    ("GET", "/api/entregas/{entrega_id}"),
    ("GET", "/api/laboratorios/{laboratorio_id}/entregas"),
    ("GET", "/api/evidencias/{evidencia_id}/enlace"),
    ("GET", "/api/archivos/{token}"),
    ("GET", "/api/portafolio/{estudiante_id}"),
    ("GET", "/api/estudiantes"),
}
ESPERADAS_EN_EVALUADOR = {
    ("POST", "/api/entregas/{entrega_id}/evaluaciones"),
    ("GET", "/api/evaluaciones/{evaluacion_id}"),
    ("GET", "/api/config-ia"),
    ("PUT", "/api/config-ia"),
    ("POST", "/api/config-ia/probar"),
    ("GET", "/api/costos"),
}


def camino(ruta: str) -> str:
    """Cambia cada {algo_id} por un id al azar, para que la ruta sea válida."""
    return re.sub(r"\{\w+_id\}", lambda _: str(uuid4()), ruta)


def test_no_hay_rutas_por_fuera_de_la_tabla():
    assert [c for c in CONSTRUIDAS if c not in TABLA] == []


def test_las_rutas_de_este_modulo_ya_existen():
    esperadas = ESPERADAS_EN_AUTH | ESPERADAS_EN_RUBRICAS | ESPERADAS_EN_ENTREGAS | ESPERADAS_EN_EVALUADOR
    assert set(CONSTRUIDAS) >= esperadas


@pytest.mark.parametrize(("metodo", "ruta"), [c for c in CONSTRUIDAS if not TABLA[c].publica])
def test_sin_sesion_responde_401(cliente, metodo, ruta):
    assert cliente.request(metodo, camino(ruta), json={}).status_code == 401


@pytest.mark.parametrize(
    ("metodo", "ruta", "rol"),
    [
        (m, r, rol.value)
        for (m, r) in CONSTRUIDAS
        for rol in Rol
        if not TABLA[m, r].publica and rol not in TABLA[m, r].roles
    ],
)
def test_con_un_rol_que_no_le_toca_responde_403(entrar, metodo, ruta, rol):
    cliente = entrar(rol)
    assert cliente.request(metodo, camino(ruta), json={}).status_code == 403


@pytest.mark.parametrize(
    ("metodo", "ruta", "rol"),
    [(m, r, rol.value) for (m, r) in CONSTRUIDAS for rol in Rol if rol in TABLA[m, r].roles],
)
def test_con_el_rol_correcto_no_responde_401_ni_403(entrar, metodo, ruta, rol):
    cliente = entrar(rol)
    assert cliente.request(metodo, camino(ruta), json={}).status_code not in {401, 403}


def test_el_rol_sale_de_la_base_y_no_de_lo_que_mande_el_navegador(entrar):
    cliente = entrar("estudiante")
    r = cliente.get("/api/usuarios", headers={"X-Rol": "administrador"}, params={"rol": "administrador"})
    assert r.status_code == 403


def test_si_le_quitan_el_rol_pierde_el_acceso_de_inmediato(entrar, db):
    from app.modelos import Usuario

    cliente = entrar("administrador")
    assert cliente.get("/api/usuarios").status_code == 200
    db.get(Usuario, cliente.usuario.id).rol = "estudiante"
    db.commit()
    assert cliente.get("/api/usuarios").status_code == 403


def test_cabeceras_de_seguridad(cliente):
    r = cliente.get("/api/yo")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "referrer-policy" in r.headers


def test_cors_solo_acepta_el_origen_propio(cliente):
    ok = cliente.options(
        "/api/yo", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    malo = cliente.options(
        "/api/yo", headers={"Origin": "https://sitio-malo.co", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in malo.headers


def test_las_rutas_que_el_estudiante_solo_ve_publicadas_estan_marcadas():
    marcadas = {(r.metodo, r.ruta) for r in RUTAS if r.solo_publicado}
    assert marcadas == {
        ("GET", "/api/evaluaciones/{evaluacion_id}/publicada"),
        ("GET", "/api/informe/{estudiante_id}"),
        ("GET", "/api/informe/{estudiante_id}/pdf"),
        ("GET", "/api/mapa/{estudiante_id}"),
    }
    assert all(Rol.ESTUDIANTE in TABLA[c].roles and TABLA[c].solo_dueno for c in marcadas)
