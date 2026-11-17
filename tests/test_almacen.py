"""Almacén de archivos y enlaces firmados (RNF-07)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest

from app import almacen as a
from app.config import ajustes

RUTA = a.ruta_de(uuid.uuid4(), uuid.uuid4())


# ---------- Local ----------


def test_guarda_lee_y_borra(tmp_path):
    local = a.AlmacenLocal(tmp_path)
    local.guardar(RUTA, b"hola", "text/plain")
    assert local.leer(RUTA) == b"hola"
    local.borrar(RUTA)
    with pytest.raises(FileNotFoundError):
        local.leer(RUTA)


def test_nunca_pisa_un_archivo_que_ya_existe(tmp_path):
    local = a.AlmacenLocal(tmp_path)
    local.guardar(RUTA, b"uno", "text/plain")
    with pytest.raises(FileExistsError):
        local.guardar(RUTA, b"dos", "text/plain")


@pytest.mark.parametrize("ruta", ["../fuera", "entregas/../../x", "entregas/a/b", "/etc/passwd"])
def test_no_acepta_rutas_que_no_arma_el_backend(tmp_path, ruta):
    with pytest.raises(ValueError):
        a.AlmacenLocal(tmp_path).guardar(ruta, b"x", "text/plain")


def test_el_enlace_local_se_puede_leer_y_trae_la_ruta(tmp_path):
    enlace = a.AlmacenLocal(tmp_path).enlace(RUTA, "informe.pdf")
    assert enlace.startswith("/api/archivos/")
    datos = a.leer_token(enlace.rsplit("/", 1)[1])
    assert datos["ruta"] == RUTA
    assert datos["nombre"] == "informe.pdf"


def test_un_enlace_vencido_no_sirve():
    vencido = jwt.encode(
        {
            "ruta": RUTA,
            "nombre": "x",
            "aud": a.AUDIENCIA_ARCHIVO,
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        ajustes().jwt_secreto,
        algorithm="HS256",
    )
    assert a.leer_token(vencido) is None


def test_un_enlace_firmado_con_otra_llave_no_sirve():
    falso = jwt.encode(
        {
            "ruta": RUTA,
            "nombre": "x",
            "aud": a.AUDIENCIA_ARCHIVO,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "otra-llave-que-no-es-la-de-la-app-xxxxxxxx",
        algorithm="HS256",
    )
    assert a.leer_token(falso) is None


def test_un_token_de_sesion_no_sirve_como_enlace(crear_usuario):
    from app.api import seguridad

    sesion = seguridad.crear_token(crear_usuario("estudiante"))
    assert a.leer_token(sesion) is None


def test_un_enlace_con_ruta_cambiada_no_sirve():
    malo = jwt.encode(
        {
            "ruta": "../../etc/passwd",
            "nombre": "x",
            "aud": a.AUDIENCIA_ARCHIVO,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        ajustes().jwt_secreto,
        algorithm="HS256",
    )
    assert a.leer_token(malo) is None


# ---------- Supabase (simulado, sin internet) ----------

URL = "https://abcdefghijklmnop.supabase.co"


def _supabase(manejar):
    pedidos = []

    def transporte(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return manejar(request)

    cliente = httpx.Client(transport=httpx.MockTransport(transporte))
    return a.AlmacenSupabase(URL, "llave-de-servicio", "evidencias", cliente=cliente), pedidos


def test_supabase_sube_al_bucket_privado_con_la_llave():
    almacen, pedidos = _supabase(lambda r: httpx.Response(200, json={"Key": "x"}))
    almacen.guardar(RUTA, b"pdf", "application/pdf")
    pedido = pedidos[0]
    assert pedido.method == "POST"
    assert str(pedido.url) == f"{URL}/storage/v1/object/evidencias/{RUTA}"
    assert pedido.headers["authorization"] == "Bearer llave-de-servicio"
    assert pedido.headers["x-upsert"] == "false"
    assert pedido.content == b"pdf"


def test_supabase_firma_un_enlace_de_5_minutos():
    firmado = f"/object/sign/evidencias/{RUTA}?token=abc"
    almacen, pedidos = _supabase(lambda r: httpx.Response(200, json={"signedURL": firmado}))
    enlace = almacen.enlace(RUTA, "mi informe.pdf")
    assert json.loads(pedidos[0].content) == {"expiresIn": a.VIGENCIA_ENLACE_SEG}
    assert enlace == f"{URL}/storage/v1{firmado}&download=mi%20informe.pdf"


def test_si_supabase_falla_se_avisa_sin_mostrar_la_respuesta():
    almacen, _ = _supabase(lambda r: httpx.Response(500, text="detalle interno con secretos"))
    with pytest.raises(a.AlmacenNoDisponible) as error:
        almacen.guardar(RUTA, b"x", "application/pdf")
    assert "secretos" not in str(error.value)


def test_si_supabase_devuelve_un_enlace_raro_no_se_usa():
    almacen, _ = _supabase(lambda r: httpx.Response(200, json={"signedURL": "https://otro-sitio.co/x"}))
    with pytest.raises(a.AlmacenNoDisponible):
        almacen.enlace(RUTA, "x.pdf")


@pytest.mark.parametrize("url", ["", "pendiente", "http://abcdefghijklmnop.supabase.co", "https://evil.co"])
def test_la_llave_solo_va_a_una_direccion_de_supabase(url):
    with pytest.raises(a.AlmacenNoDisponible):
        a.AlmacenSupabase(url, "llave", "evidencias")


def test_sin_llave_no_hay_supabase():
    with pytest.raises(a.AlmacenNoDisponible):
        a.AlmacenSupabase(URL, "", "evidencias")


def test_en_produccion_no_se_usa_la_carpeta_local(monkeypatch):
    from app.config import Ajustes

    datos = Ajustes(
        entorno="produccion",
        jwt_secreto="x" * 40,
        database_url="postgresql://u:c@h/db",
        origenes_permitidos="https://app.onrender.com",
        almacen="local",
    )
    monkeypatch.setattr(a, "ajustes", lambda: datos)
    with pytest.raises(a.AlmacenNoDisponible, match="Supabase"):
        a.crear_almacen()


def test_la_app_usa_un_solo_almacen(monkeypatch):
    a.obtener_almacen.cache_clear()
    try:
        assert a.obtener_almacen() is a.obtener_almacen()
    finally:
        a.obtener_almacen.cache_clear()


@pytest.mark.parametrize("pegada", [URL + "\n", URL + " ", "  " + URL + "/\r\n", URL + "/"])
def test_los_espacios_y_saltos_de_linea_de_los_bordes_se_recortan(pegada):
    """Al pegar el valor en Render se cuelan espacios o un salto de línea al final."""
    almacen = a.AlmacenSupabase(pegada, "  llave \n", "evidencias")
    assert almacen.base == URL + "/storage/v1"
    assert almacen._llave == "llave"


@pytest.mark.parametrize(
    "url",
    [
        URL + "\nhttps://evil.co",
        URL + "/rest/v1",
        "postgresql://u:c@db.abcdefghijklmnop.supabase.co:5432/postgres",
    ],
)
def test_lo_que_sobra_despues_de_la_direccion_no_pasa(url):
    with pytest.raises(a.AlmacenNoDisponible, match="SUPABASE_URL") as error:
        a.AlmacenSupabase(url, "llave", "evidencias")
    assert "evil" not in str(error.value) and "u:c" not in str(error.value)  # nunca el valor


def test_el_aviso_dice_que_falta_la_llave():
    with pytest.raises(a.AlmacenNoDisponible, match="SUPABASE_SERVICE_KEY"):
        a.AlmacenSupabase(URL, "   ", "evidencias")


@pytest.mark.parametrize(
    "respuesta", [httpx.Response(200, text="no es json"), httpx.Response(200, json=["lista"])]
)
def test_si_supabase_responde_algo_raro_al_firmar_se_avisa(respuesta):
    almacen, _ = _supabase(lambda r: respuesta)
    with pytest.raises(a.AlmacenNoDisponible):
        almacen.enlace(RUTA, "x.pdf")
