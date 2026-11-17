"""Descarga segura de GitHub (SSRF, OWASP A10) y tamaño de las imágenes (RF-09)."""

import struct

import httpx
import pytest
from archivos_prueba import png, zip_codigo

from app.archivos import ArchivoNoValido
from app.evaluador import github, imagenes

REPO = "https://github.com/ana/agente-archivos"


def _cliente(manejar):
    pedidos = []

    def transporte(request: httpx.Request) -> httpx.Response:
        pedidos.append(str(request.url))
        return manejar(request)

    return httpx.Client(transport=httpx.MockTransport(transporte), follow_redirects=False), pedidos


# ---------- GitHub ----------


def test_sigue_la_redireccion_a_codeload_y_baja_el_zip():
    contenido = zip_codigo()

    def manejar(request):
        if request.url.host == "github.com":
            return httpx.Response(
                302,
                headers={"location": "https://codeload.github.com/ana/agente-archivos/zip/refs/heads/main"},
            )
        return httpx.Response(200, content=contenido)

    cliente, pedidos = _cliente(manejar)
    assert github.bajar_zip(REPO, cliente) == contenido
    assert pedidos[0] == "https://github.com/ana/agente-archivos/archive/HEAD.zip"


@pytest.mark.parametrize(
    "destino",
    [
        "https://evil.co/x.zip",
        "http://codeload.github.com/x.zip",
        "https://169.254.169.254/latest",
        "https://user@github.com/x",
    ],
)
def test_no_sigue_redirecciones_a_otros_sitios(destino):
    cliente, pedidos = _cliente(lambda r: httpx.Response(302, headers={"location": destino}))
    with pytest.raises(ArchivoNoValido, match="No se pudo bajar"):
        github.bajar_zip(REPO, cliente)
    assert len(pedidos) == 1  # nunca llegó a pedir el destino


def test_un_repositorio_privado_o_que_no_existe_da_aviso():
    cliente, _ = _cliente(lambda r: httpx.Response(404))
    with pytest.raises(ArchivoNoValido, match="público"):
        github.bajar_zip(REPO, cliente)


def test_un_repositorio_muy_grande_se_corta_mientras_baja(monkeypatch):
    monkeypatch.setattr(github, "MAXIMO_BYTES", 1000)
    cliente, _ = _cliente(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(ArchivoNoValido, match="pesa más"):
        github.bajar_zip(REPO, cliente)


def test_demasiadas_redirecciones_se_cortan():
    cliente, pedidos = _cliente(
        lambda r: httpx.Response(302, headers={"location": "https://github.com/otra/vez"})
    )
    with pytest.raises(ArchivoNoValido):
        github.bajar_zip(REPO, cliente)
    assert len(pedidos) == github.MAXIMO_REDIRECCIONES + 1


def test_si_github_no_responde_da_aviso():
    def caido(request):
        raise httpx.ConnectError("sin red")

    cliente, _ = _cliente(caido)
    with pytest.raises(ArchivoNoValido, match="No se pudo bajar"):
        github.bajar_zip(REPO, cliente)


def test_usuario_y_repositorio_del_enlace():
    assert github.partes("https://github.com/ana/agente.git") == ("ana", "agente")
    with pytest.raises(ArchivoNoValido):
        github.partes("https://gitlab.com/ana/agente")


# ---------- Imágenes ----------


def test_lee_el_tamano_de_una_png():
    ancho, alto = imagenes.dimensiones(png())
    assert ancho > 0 and alto > 0


def test_lee_el_tamano_de_una_jpg():
    import pymupdf

    doc = pymupdf.open()
    pagina = doc.new_page(width=120, height=80)
    jpg = pagina.get_pixmap().tobytes("jpeg")
    assert imagenes.dimensiones(jpg) == (120, 80)


def test_una_png_que_dice_medir_50000_pixeles_no_se_describe():
    falsa = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", 50_000, 50_000)
        + b"\x08\x02\x00\x00\x00"
    )
    with pytest.raises(ArchivoNoValido, match="4096"):
        imagenes.revisar(falsa)


def _riff(trozo: bytes, datos: bytes) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(datos))
        + b"WEBP"
        + trozo
        + struct.pack("<I", len(datos))
        + datos
    )


@pytest.mark.parametrize(
    ("webp", "esperado"),
    [
        # VP8X: ancho-1 y alto-1 en 3 bytes cada uno
        (_riff(b"VP8X", b"\x00" * 4 + (639).to_bytes(3, "little") + (479).to_bytes(3, "little")), (640, 480)),
        # VP8 (con pérdida): etiqueta de cuadro, código de inicio y luego ancho y alto
        (_riff(b"VP8 ", b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 320, 200)), (320, 200)),
        # VP8L (sin pérdida): firma 0x2f y 14 bits por lado
        (_riff(b"VP8L", b"\x2f" + (99 | (49 << 14)).to_bytes(4, "little")), (100, 50)),
    ],
    ids=["vp8x", "vp8", "vp8l"],
)
def test_lee_el_tamano_de_una_webp(webp, esperado):
    assert imagenes.dimensiones(webp) == esperado


@pytest.mark.parametrize(
    "cortada",
    [
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00",
        b"\xff\xd8\xff\xc0\x00\x11\x08\x00",
        b"RIFF\x00\x00\x00\x00WEBPVP8X",
    ],
    ids=["png", "jpg", "webp"],
)
def test_una_imagen_cortada_da_aviso_y_no_struct_error(cortada):
    with pytest.raises(ArchivoNoValido):
        imagenes.dimensiones(cortada)


def test_lo_que_no_es_imagen_no_se_describe():
    with pytest.raises(ArchivoNoValido):
        imagenes.revisar(b"no soy una imagen")
