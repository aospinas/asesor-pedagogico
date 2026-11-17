"""Clave temporal, último administrador y el comando del primer administrador (RF-02)."""

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app import crear_admin
from app.api.usuarios import _queda_otro_administrador
from app.crear_admin import crear_administrador
from app.db import BaseNoDisponible
from app.modelos import Auditoria, Usuario
from tests.conftest import CLAVE

TEMPORAL = "temporal-clave-9"


# ---------- Clave temporal para quien olvidó la suya ----------


def test_el_administrador_pone_una_clave_temporal_y_el_usuario_debe_cambiarla(entrar, nuevo_cliente):
    admin = entrar("administrador")
    docente = entrar("docente")
    ruta = f"/api/usuarios/{docente.usuario.id}/clave-temporal"

    assert admin.post(ruta, json={"contrasena": TEMPORAL}).status_code == 204
    assert docente.get("/api/yo").status_code == 401  # su sesión vieja se cerró

    nuevo = nuevo_cliente()
    correo = "docente@umanizales.edu.co"
    assert nuevo.post("/api/sesion", json={"correo": correo, "contrasena": CLAVE}).status_code == 401
    r = nuevo.post("/api/sesion", json={"correo": correo, "contrasena": TEMPORAL})
    assert r.status_code == 200
    assert r.json()["debe_cambiar_contrasena"] is True


def test_la_clave_temporal_desbloquea_la_cuenta(entrar, nuevo_cliente, crear_usuario):
    admin = entrar("administrador")
    usuario = crear_usuario("estudiante")
    datos = {"correo": usuario.correo, "contrasena": "mala-mala-mala"}
    bloqueado = nuevo_cliente("203.0.113.20")
    assert [bloqueado.post("/api/sesion", json=datos).status_code for _ in range(6)][-1] == 429

    assert (
        admin.post(f"/api/usuarios/{usuario.id}/clave-temporal", json={"contrasena": TEMPORAL}).status_code
        == 204
    )
    r = bloqueado.post("/api/sesion", json={"correo": usuario.correo, "contrasena": TEMPORAL})
    assert r.status_code == 200


def test_la_clave_temporal_queda_en_la_auditoria_sin_la_clave(entrar, db):
    admin = entrar("administrador")
    docente = entrar("docente")
    admin.post(f"/api/usuarios/{docente.usuario.id}/clave-temporal", json={"contrasena": TEMPORAL})
    fila = db.query(Auditoria).filter_by(accion="clave_temporal_puesta").one()
    assert fila.usuario_id == admin.usuario.id
    assert fila.entidad_id == str(docente.usuario.id)
    assert TEMPORAL not in str(fila.detalle)


def test_la_clave_temporal_tiene_las_mismas_reglas_y_no_sirve_para_uno_mismo(entrar):
    admin = entrar("administrador")
    docente = entrar("docente")
    ruta = f"/api/usuarios/{docente.usuario.id}/clave-temporal"
    assert admin.post(ruta, json={"contrasena": "corta"}).status_code == 422
    assert (
        admin.post(
            f"/api/usuarios/{admin.usuario.id}/clave-temporal", json={"contrasena": TEMPORAL}
        ).status_code
        == 400
    )
    assert docente.post(ruta, json={"contrasena": TEMPORAL}).status_code == 403


# ---------- Siempre queda un administrador ----------


def test_un_administrador_puede_quitarle_el_rol_a_otro(entrar):
    ana = entrar("administrador", correo="ana@umanizales.edu.co")
    beto = entrar("administrador", correo="beto@umanizales.edu.co")
    assert ana.patch(f"/api/usuarios/{beto.usuario.id}", json={"rol": "docente"}).status_code == 200
    assert beto.get("/api/usuarios").status_code == 403
    assert ana.get("/api/usuarios").status_code == 200


def test_solo_cuentan_los_administradores_activos(crear_usuario, db):
    # Por la API un administrador no puede quitarse su propio rol, así que el caso
    # "queda uno solo" únicamente pasa cuando dos cambios se cruzan. Se prueba la regla directa.
    ana = crear_usuario("administrador", correo="ana@umanizales.edu.co")
    beto = crear_usuario("administrador", correo="beto@umanizales.edu.co")
    assert _queda_otro_administrador(db, ana) is True

    crear_usuario("administrador", correo="carla@umanizales.edu.co", activo=False)  # inactiva: no cuenta
    crear_usuario("docente", correo="dora@umanizales.edu.co")  # otro rol: no cuenta
    beto.rol = "docente"
    db.commit()
    assert _queda_otro_administrador(db, ana) is False


def test_no_se_puede_quitar_al_ultimo_administrador(entrar, db, monkeypatch):
    ana = entrar("administrador", correo="ana@umanizales.edu.co")
    beto = entrar("administrador", correo="beto@umanizales.edu.co")
    # Simula el cruce: cuando Ana va a degradar a Beto, ya no queda nadie más.
    monkeypatch.setattr("app.api.usuarios._queda_otro_administrador", lambda db, usuario: False)
    r = ana.patch(f"/api/usuarios/{beto.usuario.id}", json={"rol": "docente"})
    assert r.status_code == 400
    assert "al menos un administrador" in r.json()["detail"]
    assert ana.patch(f"/api/usuarios/{beto.usuario.id}", json={"activo": False}).status_code == 400
    assert db.get(Usuario, beto.usuario.id).rol == "administrador"
    # Cambiar solo el nombre de un administrador sí se puede
    assert ana.patch(f"/api/usuarios/{beto.usuario.id}", json={"nombre": "Beto B."}).status_code == 200


# ---------- Comando del primer administrador ----------


def test_crear_el_primer_administrador(db):
    admin = crear_administrador(db, "Andrés", "Andres@UManizales.edu.co", CLAVE)
    guardado = db.get(Usuario, admin.id)
    assert guardado.correo == "andres@umanizales.edu.co"
    assert guardado.rol == "administrador"
    assert guardado.debe_cambiar_contrasena is False
    assert guardado.hash_contrasena.startswith("$2b$")
    assert db.query(Auditoria).filter_by(accion="administrador_creado").count() == 1

    with pytest.raises(ValueError, match="Ya existe"):
        crear_administrador(db, "Otro", "andres@umanizales.edu.co", CLAVE)
    with pytest.raises(ValidationError):
        crear_administrador(db, "Otro", "otro@umanizales.edu.co", "corta")


def responder(monkeypatch, nombre, correo, claves):
    textos = iter([nombre, correo])
    secretos = iter(claves)
    monkeypatch.setattr("builtins.input", lambda _: next(textos))
    monkeypatch.setattr(crear_admin.getpass, "getpass", lambda _: next(secretos))


def test_el_comando_avisa_si_las_claves_no_coinciden(monkeypatch, capsys):
    responder(monkeypatch, "Andrés", "andres@umanizales.edu.co", [CLAVE, "otra-clave-distinta"])
    assert crear_admin.main() == 1
    assert "no coinciden" in capsys.readouterr().out


@pytest.mark.parametrize("error", [BaseNoDisponible("x"), OperationalError("select 1", {}, Exception("x"))])
def test_el_comando_avisa_claro_si_la_base_no_responde(monkeypatch, capsys, error):
    responder(monkeypatch, "Andrés", "andres@umanizales.edu.co", [CLAVE, CLAVE])

    def sin_base():
        raise error

    monkeypatch.setattr(crear_admin, "motor", sin_base)
    assert crear_admin.main() == 1
    salida = capsys.readouterr().out
    assert "No se pudo conectar" in salida
    assert "Traceback" not in salida
    assert CLAVE not in salida


def test_el_comando_explica_los_datos_malos_sin_repetir_la_clave(monkeypatch, capsys, motor):
    responder(monkeypatch, "Andrés", "no-es-correo", ["corta", "corta"])
    monkeypatch.setattr(crear_admin, "motor", lambda: motor)
    assert crear_admin.main() == 1
    salida = capsys.readouterr().out
    assert "correo" in salida
    assert "contrasena" in salida
    assert "corta" not in salida.replace("muy corto", "")
