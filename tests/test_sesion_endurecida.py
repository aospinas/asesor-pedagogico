"""Pruebas de los arreglos de la revisión de seguridad del módulo auth (D-15)."""

import os
import threading
from datetime import timedelta
from uuid import uuid4

import jwt
import pytest

from app import main
from app.api import seguridad
from app.config import Ajustes, ajustes
from app.db import obtener_db
from app.main import app
from app.modelos import Auditoria, IntentoSesion, Usuario
from tests.conftest import CLAVE

CORREO = "estudiante@umanizales.edu.co"
MALA = {"correo": CORREO, "contrasena": "mala-mala-mala"}
BUENA = {"correo": CORREO, "contrasena": CLAVE}


def fallar(cliente, veces, datos=MALA):
    return [cliente.post("/api/sesion", json=datos).status_code for _ in range(veces)]


# ---------- Bloqueo por correo e IP ----------


def test_bloquear_desde_una_ip_no_le_cierra_la_cuenta_al_dueno(nuevo_cliente, crear_usuario):
    crear_usuario()
    atacante = nuevo_cliente("203.0.113.9")
    assert fallar(atacante, 6) == [401] * 5 + [429]
    # El dueño entra desde su propia IP aunque el atacante la tenga bloqueada desde la suya.
    assert nuevo_cliente("198.51.100.7").post("/api/sesion", json=BUENA).status_code == 200
    assert atacante.post("/api/sesion", json=BUENA).status_code == 429


def test_un_correo_que_no_existe_se_bloquea_igual_que_uno_que_si(cliente, crear_usuario):
    crear_usuario()
    no_existe = {"correo": "nadie@umanizales.edu.co", "contrasena": "mala-mala-mala"}
    con_cuenta = fallar(cliente, 6)
    sin_cuenta = fallar(cliente, 6, no_existe)
    assert con_cuenta == sin_cuenta == [401] * 5 + [429]


def test_los_intentos_con_correo_inexistente_y_los_bloqueos_quedan_en_la_auditoria(cliente, db):
    fallar(cliente, 6, {"correo": "nadie@umanizales.edu.co", "contrasena": "mala-mala-mala"})
    filas = db.query(Auditoria).all()
    assert [f.accion for f in filas].count("sesion_fallida") == 5
    assert [f.accion for f in filas].count("sesion_bloqueada") == 1
    assert all(f.usuario_id is None and f.detalle["correo"] == "nadie@umanizales.edu.co" for f in filas)
    assert "mala-mala-mala" not in str([f.detalle for f in filas])


def test_los_intentos_viejos_se_borran_solos(cliente, db, monkeypatch):
    fallar(cliente, 1, {"correo": "viejo@umanizales.edu.co", "contrasena": "mala-mala-mala"})
    real = seguridad.ahora
    monkeypatch.setattr(seguridad, "ahora", lambda: real() + timedelta(days=2))
    fallar(cliente, 1, {"correo": "nuevo@umanizales.edu.co", "contrasena": "mala-mala-mala"})
    assert {f.correo for f in db.query(IntentoSesion)} == {"nuevo@umanizales.edu.co"}


@pytest.mark.skipif(
    not os.environ.get("PRUEBAS_DATABASE_URL"), reason="La carrera solo se puede probar en PostgreSQL"
)
def test_muchas_peticiones_al_tiempo_no_evaden_el_bloqueo(nuevo_cliente, crear_usuario):
    # Antes, 28 peticiones simultáneas probaban 28 claves y la cuenta nunca se bloqueaba.
    crear_usuario()
    codigos = []
    listos = threading.Barrier(20)

    def intento():
        cliente = nuevo_cliente("203.0.113.50")
        listos.wait()
        codigos.append(cliente.post("/api/sesion", json=MALA).status_code)

    hilos = [threading.Thread(target=intento) for _ in range(20)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert codigos.count(401) == 5  # solo cinco alcanzaron a probar una clave
    assert codigos.count(429) == 15
    assert nuevo_cliente("203.0.113.50").post("/api/sesion", json=BUENA).status_code == 429


# ---------- Cerrar sesión, desactivar y reactivar ----------


def test_un_token_copiado_deja_de_servir_al_cerrar_sesion(entrar, nuevo_cliente):
    cliente = entrar("docente")
    copiado = cliente.cookies.get("sesion")
    assert cliente.delete("/api/sesion").status_code == 204

    ladron = nuevo_cliente()
    ladron.cookies.set("sesion", copiado)
    assert ladron.get("/api/yo").status_code == 401


def test_reactivar_a_un_usuario_no_revive_su_sesion_vieja(entrar):
    admin = entrar("administrador")
    estudiante = entrar("estudiante")
    ruta = f"/api/usuarios/{estudiante.usuario.id}"
    assert admin.patch(ruta, json={"activo": False}).status_code == 200
    assert admin.patch(ruta, json={"activo": True}).status_code == 200
    assert estudiante.get("/api/yo").status_code == 401


@pytest.mark.parametrize("ver", [False, "0", None, 0.0])
def test_la_version_del_token_debe_ser_un_numero_entero(cliente, crear_usuario, ver):
    usuario = crear_usuario()
    datos = {"sub": str(usuario.id), "ver": ver, "exp": 9999999999}
    cliente.cookies.set("sesion", jwt.encode(datos, ajustes().jwt_secreto, algorithm="HS256"))
    assert cliente.get("/api/yo").status_code == 401


# ---------- Clave temporal ----------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", "/api/usuarios"),
        ("POST", "/api/usuarios"),
        ("PATCH", f"/api/usuarios/{uuid4()}"),
        ("POST", f"/api/usuarios/{uuid4()}/clave-temporal"),
        ("GET", "/api/auditoria"),
    ],
)
def test_con_clave_temporal_no_se_puede_usar_ninguna_otra_ruta(entrar, metodo, ruta):
    cliente = entrar("administrador", debe_cambiar=True)
    r = cliente.request(metodo, ruta, json={})
    assert r.status_code == 403
    assert "cambiar tu contraseña" in r.json()["detail"]


def test_con_clave_temporal_si_puede_ver_sus_datos_y_salir(entrar):
    cliente = entrar("docente", debe_cambiar=True)
    assert cliente.get("/api/yo").status_code == 200
    assert cliente.delete("/api/sesion").status_code == 204


# ---------- Cambiar la contraseña tiene tope ----------


def test_adivinar_la_clave_actual_tiene_tope_y_cierra_la_sesion(entrar, db):
    cliente = entrar("docente")
    intento = {"actual": "no-es-la-actual", "nueva": "nueva-clave-22"}
    codigos = [cliente.put("/api/yo/contrasena", json=intento).status_code for _ in range(5)]
    assert codigos == [400] * 5
    assert cliente.get("/api/yo").status_code == 401  # la sesión se cerró al quinto fallo

    acciones = [f.accion for f in db.query(Auditoria)]
    assert acciones.count("contrasena_fallida") == 5
    assert "no-es-la-actual" not in str([f.detalle for f in db.query(Auditoria)])
    # La contraseña no cambió
    usuario = db.get(Usuario, cliente.usuario.id)
    assert seguridad.clave_correcta(CLAVE, usuario.hash_contrasena)


# ---------- Peticiones desde otro sitio (CSRF) ----------


@pytest.mark.parametrize(
    "origen",
    [
        "https://sitio-malo.co",
        "null",
        "",
        "HTTP://LOCALHOST:5173",
        "http://localhost:5174",
        "http://localhost:5173.sitio-malo.co",
        "https://localhost:5173",
        "http://testserver",  # ni siquiera el propio host: solo vale ORIGENES_PERMITIDOS
    ],
)
def test_origen_que_no_esta_en_la_lista_se_rechaza(entrar, origen):
    cliente = entrar("docente")
    r = cliente.delete("/api/sesion", headers={"Origin": origen})
    assert r.status_code == 403
    assert r.headers["x-content-type-options"] == "nosniff"
    assert cliente.get("/api/yo").status_code == 200


def test_falsificar_el_host_no_sirve(entrar):
    cliente = entrar("docente")
    falso = {"Origin": "https://sitio-malo.co", "Host": "sitio-malo.co"}
    assert cliente.delete("/api/sesion", headers=falso).status_code == 403


def test_sin_origen_se_mira_sec_fetch_site(entrar):
    cliente = entrar("docente")
    assert cliente.delete("/api/sesion", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert cliente.delete("/api/sesion", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204


def test_leer_datos_no_exige_origen(entrar):
    cliente = entrar("docente")
    assert cliente.get("/api/yo", headers={"Origin": "https://sitio-malo.co"}).status_code == 200


# ---------- En producción ----------


@pytest.fixture
def produccion(monkeypatch, motor):
    prod = Ajustes(
        entorno="produccion",
        jwt_secreto=ajustes().jwt_secreto,
        database_url="postgresql://x/y",
        origenes_permitidos="https://asesor.onrender.com",
        bcrypt_rondas=4,
    )
    monkeypatch.setattr(seguridad, "ajustes", lambda: prod)
    monkeypatch.setattr(main, "ajustes", lambda: prod)
    return prod


def test_en_produccion_la_cookie_solo_viaja_por_https(produccion, cliente, crear_usuario):
    crear_usuario()
    r = cliente.post("/api/sesion", json=BUENA)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-sesion=")
    partes = {p.strip().lower() for p in cookie.split(";")}
    assert {"secure", "httponly", "samesite=lax", "path=/"} <= partes
    assert not any(p.startswith("domain=") for p in partes)
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_en_produccion_no_vale_una_cookie_con_el_nombre_de_desarrollo(produccion, cliente, crear_usuario):
    usuario = crear_usuario()
    cliente.cookies.set("sesion", seguridad.crear_token(usuario))
    assert cliente.get("/api/yo").status_code == 401
    cliente.cookies.set("__Host-sesion", seguridad.crear_token(usuario))
    assert cliente.get("/api/yo").status_code == 200


def test_en_produccion_solo_vale_el_origen_https_de_la_app(produccion, entrar):
    cliente = entrar("docente")
    for origen in ("http://localhost:5173", "http://asesor.onrender.com"):
        assert cliente.put("/api/yo/contrasena", json={}, headers={"Origin": origen}).status_code == 403


# ---------- Errores ----------


def test_un_error_inesperado_no_muestra_detalles_y_lleva_cabeceras(cliente):
    def explota():
        raise RuntimeError("detalle interno con hash_contrasena=$2b$abc")

    app.dependency_overrides[obtener_db] = explota
    r = cliente.post("/api/sesion", json=BUENA)
    assert r.status_code == 500
    assert r.json() == {"detail": "Ocurrió un error. Intenta de nuevo."}
    assert "$2b$" not in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_direccion_o_accion_que_no_existe_responde_en_espanol(cliente):
    assert cliente.get("/api/no-existe").json() == {"detail": "Esa dirección no existe."}
    r = cliente.put("/api/sesion", json={})
    assert r.status_code == 405
    assert r.json() == {"detail": "Esa acción no se puede hacer aquí."}


def test_los_errores_de_datos_salen_en_espanol(entrar):
    admin = entrar("administrador")
    r = admin.post(
        "/api/usuarios",
        json={"nombre": "", "correo": "no-es-correo", "contrasena": "corta", "rol": "jefe"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Revisa los datos enviados."
    mensajes = {e["campo"]: e["mensaje"] for e in r.json()["errores"]}
    assert mensajes == {
        "nombre": "Es muy corto. Mínimo de caracteres: 1.",
        "correo": "No tiene el formato esperado.",
        "contrasena": "Es muy corto. Mínimo de caracteres: 10.",
        "rol": "No es una de las opciones permitidas.",
    }

    larga = admin.post(
        "/api/usuarios",
        json={"nombre": "Ana", "correo": "ana@umanizales.edu.co", "contrasena": "ñ" * 40, "rol": "docente"},
    )
    assert larga.json()["errores"] == [
        {"campo": "contrasena", "mensaje": "La contraseña es demasiado larga."}
    ]

    assert admin.post("/api/usuarios", json={}).json()["errores"][0]["mensaje"] == "Falta este dato."
    assert admin.patch("/api/usuarios/no-es-id", json={}).json()["errores"][0]["mensaje"] == (
        "No es un identificador válido."
    )


def test_un_dato_que_no_se_esperaba_no_se_devuelve_ni_por_su_nombre(cliente):
    datos = BUENA | {"S3creta-clave-llave": "valor-secreto"}
    r = cliente.post("/api/sesion", json=datos)
    assert r.status_code == 422
    assert "S3creta" not in r.text
    assert "valor-secreto" not in r.text
    assert r.json()["errores"] == [{"campo": "", "mensaje": "Hay un dato que no se esperaba."}]
