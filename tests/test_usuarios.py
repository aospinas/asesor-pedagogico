"""Gestión de usuarios por el administrador (RF-02, CU-09)."""

from uuid import uuid4

from tests.conftest import CLAVE


def nuevo(**cambios):
    base = {
        "nombre": "Laura Docente",
        "correo": "laura@umanizales.edu.co",
        "contrasena": CLAVE,
        "rol": "docente",
    }
    return base | cambios


def test_el_administrador_crea_un_docente_que_luego_puede_entrar(entrar, nuevo_cliente):
    admin = entrar("administrador")
    r = admin.post("/api/usuarios", json=nuevo())
    assert r.status_code == 201
    creado = r.json()
    assert creado["rol"] == "docente"
    assert creado["activo"] is True
    assert set(creado) == {"id", "nombre", "correo", "rol", "activo", "foto_url"}

    docente = nuevo_cliente()
    r = docente.post("/api/sesion", json={"correo": "laura@umanizales.edu.co", "contrasena": CLAVE})
    assert r.status_code == 200
    # La clave la puso el administrador: debe cambiarla antes de seguir.
    assert r.json()["debe_cambiar_contrasena"] is True


def test_correo_repetido_se_rechaza_aunque_cambien_las_mayusculas(entrar):
    admin = entrar("administrador")
    assert admin.post("/api/usuarios", json=nuevo()).status_code == 201
    r = admin.post("/api/usuarios", json=nuevo(correo="LAURA@umanizales.edu.co"))
    assert r.status_code == 409


def test_contrasena_corta_se_rechaza(entrar):
    admin = entrar("administrador")
    assert admin.post("/api/usuarios", json=nuevo(contrasena="corta")).status_code == 422


def test_listar_usuarios_no_muestra_contrasenas(entrar):
    admin = entrar("administrador")
    admin.post("/api/usuarios", json=nuevo())
    r = admin.get("/api/usuarios")
    assert r.status_code == 200
    assert {u["correo"] for u in r.json()} == {"administrador@umanizales.edu.co", "laura@umanizales.edu.co"}
    assert "hash" not in r.text
    assert "$2b$" not in r.text


def test_desactivar_a_un_estudiante_le_impide_entrar(entrar, nuevo_cliente):
    admin = entrar("administrador")
    estudiante = entrar("estudiante")
    assert estudiante.get("/api/yo").status_code == 200

    r = admin.patch(f"/api/usuarios/{estudiante.usuario.id}", json={"activo": False})
    assert r.status_code == 200
    assert r.json()["activo"] is False

    assert estudiante.get("/api/yo").status_code == 401
    otro = nuevo_cliente()
    datos = {"correo": "estudiante@umanizales.edu.co", "contrasena": CLAVE}
    assert otro.post("/api/sesion", json=datos).status_code == 401


def test_cambiar_el_rol(entrar):
    admin = entrar("administrador")
    estudiante = entrar("estudiante")
    r = admin.patch(f"/api/usuarios/{estudiante.usuario.id}", json={"rol": "docente"})
    assert r.status_code == 200
    assert estudiante.get("/api/yo").json()["usuario"]["rol"] == "docente"


def test_el_administrador_no_puede_quitarse_el_rol_ni_desactivarse(entrar):
    admin = entrar("administrador")
    yo = admin.usuario.id
    assert admin.patch(f"/api/usuarios/{yo}", json={"rol": "docente"}).status_code == 400
    assert admin.patch(f"/api/usuarios/{yo}", json={"activo": False}).status_code == 400
    assert admin.patch(f"/api/usuarios/{yo}", json={"nombre": "Otro Nombre"}).status_code == 200
    assert admin.get("/api/usuarios").status_code == 200


def test_usuario_que_no_existe_da_404(entrar):
    admin = entrar("administrador")
    assert admin.patch(f"/api/usuarios/{uuid4()}", json={"activo": False}).status_code == 404
    assert admin.patch("/api/usuarios/no-es-un-id", json={"activo": False}).status_code == 422


def test_no_se_puede_cambiar_el_correo_ni_la_contrasena_de_otro(entrar):
    admin = entrar("administrador")
    estudiante = entrar("estudiante")
    ruta = f"/api/usuarios/{estudiante.usuario.id}"
    assert admin.patch(ruta, json={"contrasena": "nueva-clave-22"}).status_code == 422
    assert admin.patch(ruta, json={"correo": "otro@umanizales.edu.co"}).status_code == 422


def test_docente_y_estudiante_no_gestionan_usuarios(entrar):
    for rol in ("docente", "estudiante"):
        cliente = entrar(rol)
        assert cliente.get("/api/usuarios").status_code == 403
        assert cliente.post("/api/usuarios", json=nuevo()).status_code == 403
