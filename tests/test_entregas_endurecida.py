"""Arreglos de la revisión del módulo entregas (Puerta 2, D-17): memoria, topes y auditoría."""

import io
import threading
import time
import zipfile

import pytest
from archivos_prueba import pdf, zip_codigo
from sqlalchemy import inspect
from test_entregas import REPO, subir

from app.api import entregas as modulo
from app.archivos import ArchivoNoValido, diapositivas
from app.archivos import pdf as lector_pdf
from app.archivos import zip as lector_zip
from app.modelos import Auditoria, Evidencia

# ---------- Memoria y topes de texto ----------


def test_el_texto_del_pdf_nunca_pasa_del_tope():
    lectura = lector_pdf.leer_paginas(
        pdf("palabra " * 60, paginas=3), maximo_paginas=10, maximo_caracteres=100
    )
    assert lectura.recortado is True
    assert sum(len(p) for p in lectura.paginas) == 100


def test_un_pdf_corto_no_se_marca_como_recortado():
    lectura = lector_pdf.leer_paginas(pdf(), maximo_paginas=10, maximo_caracteres=10_000)
    assert lectura.recortado is False


def test_el_informe_recortado_lo_dice_en_el_resumen(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    monkeypatch.setattr(modulo, "MAXIMO_CARACTERES_INFORME", 40)
    r = subir(entrar("estudiante"), laboratorio, informe=pdf(paginas=3), enlace=REPO)
    assert r.status_code == 201, r.text
    evidencia = r.json()["evidencias"][0]
    assert "recortó" in evidencia["resumen"]
    fila = db.get(Evidencia, modulo.uuid.UUID(evidencia["id"]))
    assert fila.texto_extraido["recortado"] is True
    assert sum(len(p) for p in fila.texto_extraido["paginas"]) <= 40


def test_una_rubrica_en_pdf_mas_larga_que_el_tope_se_rechaza(monkeypatch):
    from app.rubricas import extraer

    monkeypatch.setattr(extraer, "MAXIMO_CARACTERES", 50)
    with pytest.raises(extraer.RubricaMuyLarga):
        extraer.extraer_texto(pdf("criterio " * 40))


def _pptx_con_diapositiva(xml: str) -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        z.writestr("ppt/slides/slide1.xml", xml)
    return memoria.getvalue()


def test_un_pptx_con_una_diapositiva_enorme_se_rechaza_rapido():
    """Antes, 164 KB así pedían 265 MB de memoria con python-pptx (hallazgo alto)."""
    contenido = _pptx_con_diapositiva("<a:t>x</a:t>" * 300_000)
    assert len(contenido) < 200_000
    inicio = time.monotonic()
    with pytest.raises(ArchivoNoValido, match="demasiado grande"):
        diapositivas.leer_diapositivas(contenido)
    assert time.monotonic() - inicio < 2


def test_el_pptx_se_lee_en_orden_y_con_caracteres_especiales():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        z.writestr("ppt/slides/slide10.xml", "<a:p><a:r><a:t>Diez</a:t></a:r></a:p>")
        z.writestr("ppt/slides/slide2.xml", "<a:p><a:r><a:t>Dos &amp; tres</a:t></a:r></a:p>")
    formato, textos, recortado = diapositivas.leer_diapositivas(memoria.getvalue())
    assert (formato, textos, recortado) == ("pptx", ["Dos & tres", "Diez"], False)


def test_un_pptx_con_compresion_rara_se_rechaza():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        z.writestr("ppt/slides/slide1.xml", "<a:t>x</a:t>", compress_type=zipfile.ZIP_LZMA)
    with pytest.raises(ArchivoNoValido):
        diapositivas.leer_diapositivas(memoria.getvalue())


def test_un_zip_con_compresion_lzma_se_rechaza():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_LZMA) as z:
        z.writestr("a.py", "x = 1\n")
    with pytest.raises(ArchivoNoValido, match="compresión"):
        lector_zip.leer_zip(memoria.getvalue())


@pytest.mark.parametrize("ruta", ["a‮fdp.py", "a​b.py", "linea\nnueva.py", "</entrega>.py", 'a"b.py'])
def test_un_zip_con_rutas_con_caracteres_raros_se_rechaza(ruta):
    with pytest.raises(ArchivoNoValido, match="no se permiten"):
        lector_zip.leer_zip(zip_codigo({ruta: "x"}))


@pytest.mark.parametrize(("enviado", "visible"), [("a‮fdp.exe", "afdp.exe"), ("in​forme.pdf", "informe.pdf")])
def test_el_nombre_visible_quita_caracteres_invisibles(enviado, visible):
    assert modulo.nombre_visible(enviado, "x") == visible


def test_solo_se_lee_un_pdf_a_la_vez(monkeypatch):
    monkeypatch.setattr(lector_pdf, "_TURNO", threading.BoundedSemaphore(1))
    monkeypatch.setattr(lector_pdf, "ESPERA_TURNO_SEG", 0.01)
    lector_pdf._TURNO.acquire()  # otro PDF se está leyendo
    with pytest.raises(lector_pdf.ServidorOcupado):
        lector_pdf.leer_paginas(pdf(), maximo_paginas=5, maximo_caracteres=1000)


def test_si_hay_muchas_subidas_a_la_vez_se_pide_esperar(
    entrar, laboratorio, rubrica_lista, almacen, monkeypatch
):
    ocupado = threading.BoundedSemaphore(1)
    ocupado.acquire()
    monkeypatch.setattr(modulo, "_SUBIDAS", ocupado)
    monkeypatch.setattr(modulo, "ESPERA_TURNO_SEG", 0.01)
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 503
    assert r.json()["detail"] == modulo.OCUPADO


def test_las_listas_no_cargan_el_texto_extraido():
    assert inspect(Evidencia).attrs.texto_extraido.deferred is True


# ---------- Topes por estudiante ----------


def test_hay_un_tope_de_entregas_por_hora(entrar, laboratorio, rubrica_lista, almacen, monkeypatch):
    monkeypatch.setattr(modulo, "ENTREGAS_POR_HORA", 2)
    estudiante = entrar("estudiante")
    for _ in range(2):
        assert subir(estudiante, laboratorio, enlace=REPO).status_code == 201
    r = subir(estudiante, laboratorio, enlace=REPO)
    assert r.status_code == 429
    assert r.json()["detail"] == modulo.MUCHAS_POR_HORA


def test_hay_un_tope_de_entregas_por_laboratorio(entrar, laboratorio, rubrica_lista, almacen, monkeypatch):
    monkeypatch.setattr(modulo, "ENTREGAS_POR_LABORATORIO", 1)
    estudiante = entrar("estudiante")
    assert subir(estudiante, laboratorio, enlace=REPO).status_code == 201
    r = subir(estudiante, laboratorio, enlace=REPO)
    assert r.status_code == 409
    assert r.json()["detail"] == modulo.MUCHAS_EN_LABORATORIO


def test_el_mismo_informe_no_se_acepta_dos_veces(entrar, laboratorio, rubrica_lista, almacen):
    estudiante = entrar("estudiante")
    informe = pdf()
    assert subir(estudiante, laboratorio, informe=informe, enlace=REPO).status_code == 201
    r = subir(estudiante, laboratorio, informe=informe, enlace=REPO)
    assert r.status_code == 409
    assert r.json()["detail"] == modulo.REPETIDA
    # Otro estudiante sí puede subir un archivo igual (no se revela nada del otro)
    otro = entrar("estudiante", correo="otro@umanizales.edu.co")
    assert subir(otro, laboratorio, informe=informe, enlace=REPO).status_code == 201


def test_mas_de_6_mb_sin_sesion_se_frena_con_401(cliente, laboratorio):
    r = cliente.post(
        "/api/entregas",
        data={"laboratorio_id": str(laboratorio.id)},
        files={"informe": ("i.pdf", b"a" * (7 * 1024 * 1024))},
    )
    assert r.status_code == 401


def test_mas_de_6_mb_con_sesion_si_llega_a_la_ruta(entrar, laboratorio, rubrica_lista, almacen):
    r = entrar("estudiante").post(
        "/api/entregas",
        data={"laboratorio_id": str(laboratorio.id), "enlace_github": REPO},
        files={"informe": ("i.pdf", b"a" * (7 * 1024 * 1024))},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Informe: debe ser un PDF."


# ---------- Archivos sueltos ----------


def test_si_falla_el_segundo_archivo_se_borra_el_primero(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    from app.almacen import AlmacenNoDisponible

    original = almacen.guardar
    llamadas = []

    def guardar(ruta, contenido, tipo):
        llamadas.append(ruta)
        if len(llamadas) == 2:
            raise AlmacenNoDisponible("se cayó")
        original(ruta, contenido, tipo)

    monkeypatch.setattr(almacen, "guardar", guardar)
    r = subir(entrar("estudiante"), laboratorio, codigo=zip_codigo())
    assert r.status_code == 503
    assert len(llamadas) == 2
    assert not any(p.is_file() for p in almacen.carpeta.rglob("*"))
    assert db.query(Evidencia).count() == 0


# ---------- Auditoría ----------


def test_los_intentos_de_ver_algo_ajeno_quedan_en_la_auditoria(
    entrar, laboratorio, rubrica_lista, almacen, db
):
    ana = entrar("estudiante", correo="ana@umanizales.edu.co")
    entrega = subir(ana, laboratorio, enlace=REPO).json()
    beto = entrar("estudiante", correo="beto@umanizales.edu.co")
    beto.get(f"/api/entregas/{entrega['id']}")
    beto.get(f"/api/evidencias/{entrega['evidencias'][0]['id']}/enlace")
    beto.get(f"/api/portafolio/{ana.usuario.id}")
    filas = db.query(Auditoria).filter_by(accion="acceso_ajeno_denegado").all()
    assert sorted(f.entidad for f in filas) == ["entrega", "evidencia", "portafolio"]
    assert all(f.usuario_id == beto.usuario.id for f in filas)


def test_pedir_un_enlace_queda_en_la_auditoria(entrar, laboratorio, rubrica_lista, almacen, db):
    estudiante = entrar("estudiante")
    entrega = subir(estudiante, laboratorio, enlace=REPO).json()
    evidencia = entrega["evidencias"][0]["id"]
    estudiante.get(f"/api/evidencias/{evidencia}/enlace")
    fila = db.query(Auditoria).filter_by(accion="enlace_emitido").one()
    assert fila.entidad_id == evidencia
    assert "url" not in fila.detalle


def test_un_archivo_rechazado_queda_en_la_auditoria(entrar, laboratorio, rubrica_lista, almacen, db):
    subir(entrar("estudiante"), laboratorio, codigo=zip_codigo({"../../fuera.py": "x"}))
    fila = db.query(Auditoria).filter_by(accion="archivo_rechazado").one()
    assert fila.detalle["motivo"].startswith("Código:")


# ---------- Listas paginadas ----------


def test_mis_entregas_se_pagina(entrar, laboratorio, rubrica_lista, almacen):
    estudiante = entrar("estudiante")
    ids = [subir(estudiante, laboratorio, enlace=REPO).json()["id"] for _ in range(3)]
    primera = estudiante.get("/api/mis-entregas", params={"limite": 2}).json()
    segunda = estudiante.get("/api/mis-entregas", params={"limite": 2, "desde": 2}).json()
    assert [e["id"] for e in primera + segunda] == list(reversed(ids))


def test_el_limite_de_la_lista_tiene_tope(entrar):
    assert entrar("estudiante").get("/api/mis-entregas", params={"limite": 10_000}).status_code == 422
