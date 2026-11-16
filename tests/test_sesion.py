"""Inicio de sesión, cierre y cambio de contraseña (RF-01, RNF-06, CU-01)."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.api import seguridad
from app.config import Ajustes
from app.modelos import Usuario
from tests.conftest import CLAVE

MENSAJE = "Correo o contraseña incorrectos."


def credenciales(correo="estudiante@umanizales.edu.co", contrasena=CLAVE):
    return {"correo": correo, "contrasena": contrasena}


# ---------- Entrar ----------


def test_con_datos_correctos_entra_y_recibe_cookie_httponly(cliente, crear_usuario):
    crear_usuario("docente")
    r = cliente.post("/api/sesion", json=credenciales("docente@umanizales.edu.co"))
    assert r.status_code == 200
    assert r.json()["usuario"]["rol"] == "docente"
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("sesion=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert cliente.get("/api/yo").json()["usuario"]["correo"] == "docente@umanizales.edu.co"


def test_la_respuesta_nunca_trae_la_contrasena(cliente, crear_usuario):
    crear_usuario()
    texto = cliente.post("/api/sesion", json=credenciales()).text.lower()
    assert "hash" not in texto
    assert 'contrasena":' not in texto.replace("debe_cambiar_contrasena", "")
    assert "$2b$" not in texto


def test_el_correo_se_acepta_con_mayusculas(cliente, crear_usuario):
    crear_usuario()
    assert cliente.post("/api/sesion", json=credenciales("Estudiante@UManizales.edu.co")).status_code == 200


def test_mismo_mensaje_si_el_correo_no_existe_o_la_clave_es_mala(cliente, crear_usuario):
    crear_usuario()
    mala = cliente.post("/api/sesion", json=credenciales(contrasena="otra-clave-mala"))
    no_existe = cliente.post("/api/sesion", json=credenciales("nadie@umanizales.edu.co"))
    assert mala.status_code == no_existe.status_code == 401
    assert mala.json() == no_existe.json() == {"detail": MENSAJE}
    assert "set-cookie" not in mala.headers


def test_usuario_desactivado_no_entra(cliente, crear_usuario):
    crear_usuario(activo=False)
    r = cliente.post("/api/sesion", json=credenciales())
    assert r.status_code == 401
    assert r.json() == {"detail": MENSAJE}


def test_un_error_de_validacion_no_devuelve_lo_que_se_escribio(cliente):
    r = cliente.post("/api/sesion", json={"correo": "no-es-correo", "contrasena": "mi-clave-secreta"})
    assert r.status_code == 422
    assert "mi-clave-secreta" not in r.text
    assert "no-es-correo" not in r.text


# ---------- Bloqueo por intentos (OWASP A07) ----------


def test_a_los_5_intentos_queda_bloqueado_5_minutos(cliente, crear_usuario, monkeypatch):
    crear_usuario()
    for _ in range(5):
        assert cliente.post("/api/sesion", json=credenciales(contrasena="mala-mala-mala")).status_code == 401

    # Ya bloqueado: ni con la clave buena entra.
    r = cliente.post("/api/sesion", json=credenciales())
    assert r.status_code == 429
    assert "set-cookie" not in r.headers

    real = seguridad.ahora
    monkeypatch.setattr(seguridad, "ahora", lambda: real() + timedelta(minutes=4, seconds=50))
    assert cliente.post("/api/sesion", json=credenciales()).status_code == 429

    monkeypatch.setattr(seguridad, "ahora", lambda: real() + timedelta(minutes=5, seconds=5))
    assert cliente.post("/api/sesion", json=credenciales()).status_code == 200


def test_entrar_bien_reinicia_la_cuenta_de_intentos(cliente, crear_usuario):
    crear_usuario()
    for _ in range(4):
        cliente.post("/api/sesion", json=credenciales(contrasena="mala-mala-mala"))
    assert cliente.post("/api/sesion", json=credenciales()).status_code == 200
    for _ in range(4):
        cliente.post("/api/sesion", json=credenciales(contrasena="mala-mala-mala"))
    assert cliente.post("/api/sesion", json=credenciales()).status_code == 200


def test_limite_de_intentos_por_ip(cliente):
    codigos = [
        cliente.post("/api/sesion", json=credenciales(f"nadie{i}@umanizales.edu.co")).status_code
        for i in range(seguridad.INTENTOS_POR_IP_POR_MINUTO + 1)
    ]
    assert codigos[-1] == 429
    assert set(codigos[:-1]) == {401}


# ---------- Sesión ----------


def test_sin_sesion_no_se_ve_nada(cliente):
    assert cliente.get("/api/yo").status_code == 401


def test_cerrar_sesion_borra_la_cookie(entrar):
    cliente = entrar("docente")
    assert cliente.delete("/api/sesion").status_code == 204
    assert cliente.get("/api/yo").status_code == 401


@pytest.mark.parametrize("cookie", ["basura", "a.b.c", ""])
def test_cookie_alterada_se_rechaza(cliente, cookie):
    cliente.cookies.set("sesion", cookie)
    assert cliente.get("/api/yo").status_code == 401


def test_token_firmado_con_otro_secreto_se_rechaza(cliente, crear_usuario):
    import jwt

    usuario = crear_usuario()
    falso = jwt.encode(
        {"sub": str(usuario.id), "ver": 0, "exp": 9999999999}, "otro-secreto" * 4, algorithm="HS256"
    )
    cliente.cookies.set("sesion", falso)
    assert cliente.get("/api/yo").status_code == 401


def test_token_sin_firma_se_rechaza(cliente, crear_usuario):
    import jwt

    usuario = crear_usuario()
    sin_firma = jwt.encode({"sub": str(usuario.id), "ver": 0, "exp": 9999999999}, None, algorithm="none")
    cliente.cookies.set("sesion", sin_firma)
    assert cliente.get("/api/yo").status_code == 401


def test_sesion_vencida_se_rechaza(cliente, crear_usuario):
    usuario = crear_usuario()
    cliente.cookies.set("sesion", seguridad.crear_token(usuario, minutos=-1))
    assert cliente.get("/api/yo").status_code == 401


def test_si_desactivan_al_usuario_su_sesion_deja_de_servir(entrar, db):
    cliente = entrar("estudiante")
    assert cliente.get("/api/yo").status_code == 200
    usuario = db.get(Usuario, cliente.usuario.id)
    usuario.activo = False
    db.commit()
    assert cliente.get("/api/yo").status_code == 401


# ---------- Cambiar mi contraseña ----------


def test_cambiar_contrasena_pide_la_actual(entrar):
    cliente = entrar("docente")
    r = cliente.put("/api/yo/contrasena", json={"actual": "no-es-la-actual", "nueva": "nueva-clave-22"})
    assert r.status_code == 400
    # La vieja sigue sirviendo
    assert cliente.post("/api/sesion", json=credenciales("docente@umanizales.edu.co")).status_code == 200


def test_cambiar_contrasena_funciona_y_cierra_las_otras_sesiones(entrar, nuevo_cliente):
    cliente = entrar("docente")
    otro = nuevo_cliente()
    assert otro.post("/api/sesion", json=credenciales("docente@umanizales.edu.co")).status_code == 200

    r = cliente.put("/api/yo/contrasena", json={"actual": CLAVE, "nueva": "nueva-clave-22"})
    assert r.status_code == 204
    assert cliente.get("/api/yo").status_code == 200  # este navegador sigue adentro
    assert otro.get("/api/yo").status_code == 401  # el otro quedó afuera

    tercero = nuevo_cliente()
    assert tercero.post("/api/sesion", json=credenciales("docente@umanizales.edu.co")).status_code == 401
    nueva = credenciales("docente@umanizales.edu.co", "nueva-clave-22")
    assert tercero.post("/api/sesion", json=nueva).status_code == 200


def test_la_nueva_no_puede_ser_igual_a_la_actual(entrar):
    cliente = entrar("docente")
    assert cliente.put("/api/yo/contrasena", json={"actual": CLAVE, "nueva": CLAVE}).status_code == 400


def test_quien_debe_cambiar_la_contrasena_no_puede_hacer_nada_mas(entrar):
    cliente = entrar("administrador", debe_cambiar=True)
    assert cliente.get("/api/yo").json()["debe_cambiar_contrasena"] is True
    assert cliente.get("/api/usuarios").status_code == 403

    assert (
        cliente.put("/api/yo/contrasena", json={"actual": CLAVE, "nueva": "nueva-clave-22"}).status_code
        == 204
    )
    assert cliente.get("/api/yo").json()["debe_cambiar_contrasena"] is False
    assert cliente.get("/api/usuarios").status_code == 200


# ---------- Peticiones desde otro sitio (CSRF) ----------


def test_peticion_que_cambia_datos_desde_otro_sitio_se_rechaza(entrar):
    cliente = entrar("docente")
    r = cliente.delete("/api/sesion", headers={"Origin": "https://sitio-malo.co"})
    assert r.status_code == 403
    assert cliente.get("/api/yo").status_code == 200
    assert cliente.delete("/api/sesion", headers={"Origin": "http://localhost:5173"}).status_code == 204


# ---------- Configuración ----------


def test_en_produccion_no_arranca_con_un_secreto_corto():
    bien = {"entorno": "produccion", "database_url": "postgresql://x/y", "jwt_secreto": "s" * 32}
    bien["origenes_permitidos"] = "https://asesor.onrender.com"
    assert Ajustes(**bien)
    with pytest.raises(ValidationError):
        Ajustes(**bien | {"jwt_secreto": "corto"})
    with pytest.raises(ValidationError):
        Ajustes(**bien | {"database_url": ""})


@pytest.mark.parametrize("entorno", ["production", "Produccion", "PRODUCCION", "prod", " produccion", ""])
def test_entorno_mal_escrito_no_deja_arrancar(entorno):
    # Antes arrancaba sin avisar en modo desarrollo: cookie sin HTTPS.
    with pytest.raises(ValidationError):
        Ajustes(entorno=entorno, jwt_secreto="s" * 32)


@pytest.mark.parametrize(
    "origenes",
    ["*", "http://asesor.onrender.com", "https://asesor.onrender.com,http://localhost:5173", "", " , "],
)
def test_en_produccion_los_origenes_deben_ser_https(origenes):
    with pytest.raises(ValidationError):
        Ajustes(
            entorno="produccion",
            jwt_secreto="s" * 32,
            database_url="postgresql://x/y",
            origenes_permitidos=origenes,
        )


def test_la_direccion_de_la_base_se_adapta_al_conector():
    ajustes = Ajustes(entorno="pruebas", jwt_secreto="s" * 32, database_url="postgresql://u:c@host:5432/db")
    assert ajustes.database_url == "postgresql+psycopg://u:c@host:5432/db"


def test_el_hash_es_bcrypt_y_no_la_clave():
    resumen = seguridad.crear_hash(CLAVE)
    assert resumen.startswith("$2b$")
    assert CLAVE not in resumen
    assert seguridad.clave_correcta(CLAVE, resumen)
    assert not seguridad.clave_correcta("otra", resumen)
