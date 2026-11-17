"""Lectura segura del código en ZIP y de las diapositivas (RF-09, OWASP A08)."""

import io
import stat
import time
import zipfile

import pytest
from archivos_prueba import pdf, pptx, zip_codigo

from app.archivos import ArchivoNoValido, diapositivas
from app.archivos import zip as lector


def _zip_con(info: zipfile.ZipInfo, datos: bytes = b"x") -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr(info, datos)
    return memoria.getvalue()


def test_lee_el_arbol_y_el_texto_y_salta_los_binarios():
    resultado = lector.leer_zip(zip_codigo())
    assert resultado.arbol == ["agente/README.md", "agente/logo.png", "agente/main.py"]
    assert {a.ruta for a in resultado.archivos} == {"agente/README.md", "agente/main.py"}
    assert resultado.omitidos == [{"ruta": "agente/logo.png", "motivo": "binario"}]
    assert "def ordenar" in next(a.texto for a in resultado.archivos if a.ruta == "agente/main.py")


@pytest.mark.parametrize(
    "ruta", ["../fuera.py", "a/../../fuera.py", "/etc/passwd", "C:/Windows/x.py", "a\\..\\b.py"]
)
def test_un_zip_con_rutas_que_se_salen_se_rechaza(ruta):
    with pytest.raises(ArchivoNoValido, match="no se permiten"):
        lector.leer_zip(_zip_con(zipfile.ZipInfo(ruta)))


def test_un_zip_con_enlaces_simbolicos_se_rechaza():
    info = zipfile.ZipInfo("enlace")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ArchivoNoValido, match="enlaces"):
        lector.leer_zip(_zip_con(info, b"/etc/passwd"))


def test_un_zip_con_demasiados_archivos_se_rechaza():
    archivos = {f"a{i}.py": "x" for i in range(lector.MAXIMO_ARCHIVOS + 1)}
    with pytest.raises(ArchivoNoValido, match="más de"):
        lector.leer_zip(zip_codigo(archivos))


def test_un_zip_que_se_infla_al_abrirlo_se_rechaza_rapido():
    archivos = {f"a{i}.txt": "0" * (5 * 1024 * 1024) for i in range(5)}  # 25 MB abiertos, pocos KB cerrados
    contenido = zip_codigo(archivos)
    assert len(contenido) < 1024 * 1024
    inicio = time.monotonic()
    with pytest.raises(ArchivoNoValido, match="al abrirlo"):
        lector.leer_zip(contenido)
    assert time.monotonic() - inicio < 2


def test_un_zip_que_miente_sobre_su_tamano_se_corta():
    contenido = bytearray(zip_codigo({"grande.txt": "0" * (600 * 1024)}))
    # Se cambia el tamaño que declara el ZIP (cabecera central) para que diga 10 bytes
    i = contenido.find(b"PK\x01\x02")
    contenido[i + 24 : i + 28] = (10).to_bytes(4, "little")
    # zipfile nota que el tamaño no cuadra y el ZIP se rechaza entero: no se lee de más
    with pytest.raises(ArchivoNoValido):
        lector.leer_zip(bytes(contenido))


def test_un_zip_cifrado_se_rechaza():
    contenido = bytearray(zip_codigo({"a.py": "x = 1\n"}))
    for firma, bandera in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):  # marca de cifrado en las dos cabeceras
        i = contenido.find(firma)
        contenido[i + bandera] |= 0x01
    with pytest.raises(ArchivoNoValido, match="contraseña"):
        lector.leer_zip(bytes(contenido))


def test_un_zip_danado_da_un_aviso():
    with pytest.raises(ArchivoNoValido, match="No se pudo abrir"):
        lector.leer_zip(b"PK\x03\x04" + b"basura" * 50)


def test_lo_que_no_es_zip_se_rechaza():
    with pytest.raises(ArchivoNoValido, match="ZIP"):
        lector.leer_zip(b"no soy un zip")


def test_se_ignoran_las_carpetas_que_no_son_codigo():
    resultado = lector.leer_zip(
        zip_codigo({"app/main.py": "x = 1\n", "app/__pycache__/main.pyc": "x", ".venv/lib/a.py": "y"})
    )
    assert [a.ruta for a in resultado.archivos] == ["app/main.py"]
    assert {o["motivo"] for o in resultado.omitidos} == {"carpeta ignorada"}


def test_un_archivo_de_codigo_muy_grande_se_omite():
    resultado = lector.leer_zip(zip_codigo({"datos.csv": "1," * (lector.MAXIMO_POR_ARCHIVO), "a.py": "x"}))
    assert [a.ruta for a in resultado.archivos] == ["a.py"]
    assert resultado.omitidos == [{"ruta": "datos.csv", "motivo": "muy grande"}]


# ---------- Diapositivas ----------


def test_lee_el_texto_de_un_pptx():
    formato, textos, recortado = diapositivas.leer_diapositivas(pptx())
    assert recortado is False
    assert formato == "pptx"
    assert textos == ["Diapositiva uno: el agente", "Diapositiva dos: resultados"]


def test_lee_diapositivas_en_pdf():
    formato, textos, _ = diapositivas.leer_diapositivas(pdf("Resultados del agente", paginas=2))
    assert formato == "pdf"
    assert len(textos) == 2


def test_un_zip_que_no_es_pptx_no_sirve_como_diapositivas():
    with pytest.raises(ArchivoNoValido, match="PowerPoint"):
        diapositivas.leer_diapositivas(zip_codigo())
