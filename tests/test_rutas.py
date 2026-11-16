"""Pruebas de la tabla de rutas de la API (app/api/rutas.py)."""

import re
from pathlib import Path

from app.api.rutas import RUTAS, quien, tabla_markdown
from app.esquemas import Rol

API_MD = Path(__file__).parent.parent / "docs" / "api.md"

PUBLICAS = {
    ("GET", "/salud"),
    ("POST", "/api/sesion"),
    ("GET", "/api/proyecto"),
    ("GET", "/api/bitacora"),
}


def test_no_hay_rutas_repetidas():
    claves = [(r.metodo, r.ruta) for r in RUTAS]
    assert len(claves) == len(set(claves))


def test_toda_ruta_tiene_rol_o_es_publica():
    for r in RUTAS:
        assert r.publica != bool(r.roles), f"{r.metodo} {r.ruta}"


def test_las_rutas_publicas_son_solo_las_acordadas():
    assert {(r.metodo, r.ruta) for r in RUTAS if r.publica} == PUBLICAS


def test_metodos_y_rutas_bien_escritos():
    for r in RUTAS:
        assert r.metodo in {"GET", "POST", "PATCH", "PUT", "DELETE"}
        assert re.fullmatch(r"/[a-z0-9_{}/.\-]*", r.ruta), r.ruta
        assert r.publica or r.ruta.startswith("/api/")
        assert r.descripcion


def test_usuarios_config_y_auditoria_son_solo_del_administrador():
    for r in RUTAS:
        if r.ruta.startswith(("/api/usuarios", "/api/config-ia", "/api/auditoria", "/api/costos")):
            assert r.roles == frozenset({Rol.ADMINISTRADOR}), f"{r.metodo} {r.ruta}"


def test_el_estudiante_no_entra_a_borradores_ni_a_acciones_del_docente():
    for r in RUTAS:
        if Rol.ESTUDIANTE not in r.roles:
            continue
        propias = {"/api/sesion", "/api/entregas", "/api/yo/contrasena"}
        assert r.metodo == "GET" or r.ruta in propias, f"{r.metodo} {r.ruta}"
        if "{" in r.ruta and r.ruta.startswith(
            (
                "/api/evaluaciones",
                "/api/portafolio",
                "/api/informe",
                "/api/mapa",
                "/api/entregas/",
                "/api/evidencias",
            )
        ):
            assert r.solo_dueno, f"{r.metodo} {r.ruta}"


def test_el_administrador_no_aprueba_ni_publica():
    for r in RUTAS:
        if r.ruta.endswith(("/aprobar", "/publicar", "/ajustes", "/retroalimentacion")):
            assert r.roles == frozenset({Rol.DOCENTE}), f"{r.metodo} {r.ruta}"


def test_nadie_borra_evaluaciones_ni_rubricas():
    for r in RUTAS:
        if r.metodo == "DELETE":
            assert r.ruta == "/api/sesion", f"{r.metodo} {r.ruta}"


def test_docs_api_md_tiene_todas_las_rutas():
    texto = API_MD.read_text(encoding="utf-8")
    en_doc = set(re.findall(r"`(GET|POST|PATCH|PUT|DELETE) (/[^`]*)`", texto))
    assert en_doc == {(r.metodo, r.ruta) for r in RUTAS}


def test_docs_api_md_tiene_los_mismos_roles_y_requisitos():
    # Compara la tabla completa: ruta, para qué, quién y requisitos.
    texto = API_MD.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert tabla_markdown() in texto, "Regenera la tabla con: python -m app.api.rutas"


def test_texto_de_quien_puede_usar_cada_ruta():
    por_ruta = {(r.metodo, r.ruta): quien(r) for r in RUTAS}
    assert por_ruta[("GET", "/salud")] == "Pública (sin sesión)"
    assert por_ruta[("GET", "/api/yo")] == "Cualquiera con sesión"
    assert por_ruta[("GET", "/api/usuarios")] == "Administrador"
    assert por_ruta[("GET", "/api/portafolio/{estudiante_id}")] == "Estudiante (solo lo suyo), Docente"
    assert por_ruta[("GET", "/api/estudiantes")] == "Docente"
