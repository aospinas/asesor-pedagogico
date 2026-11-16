"""Registro de auditoría (OWASP A09, RNF-08). Fila C6 de la matriz del SRS."""

import pytest

from app.auditoria.registro import registrar
from app.modelos import Auditoria
from tests.conftest import CLAVE


def acciones(admin):
    r = admin.get("/api/auditoria")
    assert r.status_code == 200
    return r.json()


def test_entrar_y_fallar_quedan_registrados(entrar, nuevo_cliente):
    admin = entrar("administrador")
    otro = nuevo_cliente()
    otro.post(
        "/api/sesion", json={"correo": "administrador@umanizales.edu.co", "contrasena": "mala-mala-mala"}
    )

    registros = acciones(admin)
    nombres = [r["accion"] for r in registros]
    assert "sesion_iniciada" in nombres
    assert "sesion_fallida" in nombres
    assert "mala-mala-mala" not in str(registros)


def test_crear_cambiar_rol_y_desactivar_quedan_con_valor_anterior_y_nuevo(entrar):
    admin = entrar("administrador")
    creado = admin.post(
        "/api/usuarios",
        json={
            "nombre": "Laura",
            "correo": "laura@umanizales.edu.co",
            "contrasena": CLAVE,
            "rol": "estudiante",
        },
    ).json()
    admin.patch(f"/api/usuarios/{creado['id']}", json={"rol": "docente"})
    admin.patch(f"/api/usuarios/{creado['id']}", json={"activo": False})

    registros = [r for r in acciones(admin) if r["entidad_id"] == creado["id"]]
    assert sorted(r["accion"] for r in registros) == ["usuario_creado", "usuario_editado", "usuario_editado"]

    cambios = [r["detalle"] for r in registros if r["accion"] == "usuario_editado"]
    assert {"campo": "rol", "anterior": "estudiante", "nuevo": "docente"} in [
        c["cambios"][0] for c in cambios
    ]
    assert {"campo": "activo", "anterior": True, "nuevo": False} in [c["cambios"][0] for c in cambios]
    assert all(r["usuario_id"] == str(admin.usuario.id) for r in registros)
    assert CLAVE not in str(registros)


def test_cambiar_la_contrasena_queda_registrado_sin_la_clave(entrar, nuevo_cliente):
    docente = entrar("docente")
    docente.put("/api/yo/contrasena", json={"actual": CLAVE, "nueva": "nueva-clave-22"})
    admin = entrar("administrador")
    registros = acciones(admin)
    assert "contrasena_cambiada" in [r["accion"] for r in registros]
    assert "nueva-clave-22" not in str(registros)


def test_solo_el_administrador_ve_la_auditoria(entrar):
    for rol in ("docente", "estudiante"):
        assert entrar(rol).get("/api/auditoria").status_code == 403


def test_la_auditoria_sale_de_la_mas_nueva_a_la_mas_vieja_y_con_tope(entrar):
    admin = entrar("administrador")
    for i in range(3):
        admin.post(
            "/api/usuarios",
            json={
                "nombre": f"U{i}",
                "correo": f"u{i}@umanizales.edu.co",
                "contrasena": CLAVE,
                "rol": "estudiante",
            },
        )
    todos = acciones(admin)
    fechas = [r["fecha"] for r in todos]
    assert fechas == sorted(fechas, reverse=True)
    assert len(admin.get("/api/auditoria", params={"limite": 2}).json()) == 2
    assert admin.get("/api/auditoria", params={"limite": 5000}).status_code == 422


@pytest.mark.parametrize(
    "detalle",
    [
        {"contrasena": "x"},
        {"cambios": [{"campo": "hash_contrasena", "nuevo": "x"}]},
        {"datos": {"token": "x"}},
        {"API_KEY": "x"},
        {"cookie": "x"},
    ],
)
def test_no_se_pueden_guardar_secretos_en_la_auditoria(db, detalle):
    with pytest.raises(ValueError, match="secreto"):
        registrar(db, usuario_id=None, accion="prueba", entidad="usuario", detalle=detalle)
    assert db.query(Auditoria).count() == 0


def test_la_ip_solo_se_guarda_si_es_una_ip(db):
    registrar(db, usuario_id=None, accion="a", entidad="usuario", ip="testclient")
    registrar(db, usuario_id=None, accion="b", entidad="usuario", ip="203.0.113.7")
    db.commit()
    assert {r.accion: r.ip for r in db.query(Auditoria)} == {"a": None, "b": "203.0.113.7"}
