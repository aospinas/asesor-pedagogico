"""Arreglos de la segunda a la sexta revisión del módulo entregas (D-17)."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from archivos_prueba import pdf, png, pptx, zip_codigo
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from test_entregas import REPO, subir

from app.api import entregas as modulo
from app.api import seguridad
from app.archivos import ArchivoNoValido
from app.archivos import pdf as lector_pdf
from app.archivos import zip as lector_zip
from app.main import app
from app.modelos import Auditoria, Entrega

# ---------- Nombres que quedan vacíos (hallazgo alto) ----------


@pytest.mark.parametrize("nombre", [". .", ". .", ".. ..", "   ", "‮", "...."])
def test_un_nombre_que_queda_vacio_usa_el_nombre_por_defecto(nombre):
    assert modulo.nombre_visible(nombre, "informe.pdf") == "informe.pdf"


def test_un_nombre_raro_no_tumba_las_listas(entrar, laboratorio, rubrica_lista, almacen):
    estudiante = entrar("estudiante")
    r = estudiante.post(
        "/api/entregas",
        data={"laboratorio_id": str(laboratorio.id), "enlace_github": REPO},
        files={"informe": (". .", pdf(), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["evidencias"][0]["nombre"] == "informe.pdf"
    assert estudiante.get("/api/mis-entregas").status_code == 200
    assert entrar("docente").get(f"/api/laboratorios/{laboratorio.id}/entregas").status_code == 200


def test_los_saltos_de_linea_unicode_se_quitan_del_nombre():
    assert modulo.nombre_visible("a b .pdf", "x") == "ab.pdf"


@pytest.mark.parametrize("ruta", ["a b.py", "a b.py"])
def test_un_zip_con_saltos_de_linea_unicode_se_rechaza(ruta):
    with pytest.raises(ArchivoNoValido, match="no se permiten"):
        lector_zip.leer_zip(zip_codigo({ruta: "x"}))


# ---------- Índice del ZIP (antes de abrirlo) ----------


def _fin_de_indice(entradas: int, peso: int) -> bytes:
    return (
        b"PK\x05\x06"
        + b"\x00" * 6
        + entradas.to_bytes(2, "little")
        + peso.to_bytes(4, "little")
        + b"\x00" * 6
    )


def test_un_zip_que_dice_tener_demasiadas_entradas_se_rechaza_sin_abrirlo():
    contenido = b"PK\x03\x04" + b"\x00" * 100 + _fin_de_indice(60_000, 60_000 * 46)
    with pytest.raises(ArchivoNoValido, match="más de 500 partes"):
        lector_zip.leer_zip(contenido)


def test_un_zip_con_un_indice_enorme_se_rechaza():
    contenido = b"PK\x03\x04" + b"\x00" * 100 + _fin_de_indice(10, 50 * 1024 * 1024)
    with pytest.raises(ArchivoNoValido):
        lector_zip.leer_zip(contenido)


def test_un_zip_sin_registro_final_se_rechaza():
    with pytest.raises(ArchivoNoValido, match="No se pudo abrir"):
        lector_zip.leer_zip(b"PK\x03\x04" + b"\x00" * 200)


def test_un_zip_de_verdad_pasa_la_revision_del_indice():
    lector_zip.revisar_indice(zip_codigo(), lector_zip.MAXIMO_ARCHIVOS)
    lector_zip.revisar_indice(pptx(), 2000)


def test_un_word_con_indice_enorme_se_rechaza_en_rubricas():
    from app.rubricas import extraer

    contenido = b"PK\x03\x04" + b"\x00" * 100 + _fin_de_indice(60_000, 60_000 * 46)
    with pytest.raises(ArchivoNoValido, match="partes"):
        extraer.extraer_texto(contenido)


# ---------- 503 y no 500 cuando el lector de PDF está ocupado ----------


def test_una_rubrica_en_pdf_con_el_lector_ocupado_da_503(entrar, laboratorio, ia_simulada, monkeypatch):
    monkeypatch.setattr(lector_pdf, "_TURNO", threading.BoundedSemaphore(1))
    monkeypatch.setattr(lector_pdf, "ESPERA_TURNO_SEG", 0.01)
    lector_pdf._TURNO.acquire()
    r = entrar("docente").post(
        f"/api/laboratorios/{laboratorio.id}/rubrica", files={"archivo": ("r.pdf", pdf())}
    )
    assert r.status_code == 503
    assert "Intenta de nuevo" in r.json()["detail"]


# ---------- Topes que faltaban ----------


def test_los_archivos_rechazados_tambien_tienen_tope(
    entrar, laboratorio, rubrica_lista, almacen, monkeypatch
):
    monkeypatch.setattr(modulo, "RECHAZOS_POR_HORA", 2)
    estudiante = entrar("estudiante")
    for _ in range(2):
        assert subir(estudiante, laboratorio, informe=pdf(texto=None), enlace=REPO).status_code == 400
    r = subir(estudiante, laboratorio, enlace=REPO)
    assert r.status_code == 429
    assert r.json()["detail"] == modulo.MUCHOS_RECHAZOS


def test_hay_un_tope_de_megas_por_dia(entrar, laboratorio, rubrica_lista, almacen, monkeypatch):
    monkeypatch.setattr(modulo, "MEGAS_POR_DIA", 0)
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 429
    assert r.json()["detail"] == modulo.MUCHOS_MEGAS
    assert not any(p.is_file() for p in almacen.carpeta.rglob("*"))  # lo guardado se borró


def test_la_base_no_acepta_el_mismo_informe_dos_veces(db, laboratorio, rubrica_lista, crear_usuario):
    estudiante = crear_usuario("estudiante")
    datos = {
        "estudiante_id": estudiante.id,
        "laboratorio_id": laboratorio.id,
        "rubrica_version_id": rubrica_lista.id,
        "sha256_informe": "a" * 64,
    }
    db.add(Entrega(**datos))
    db.commit()
    db.add(Entrega(**datos))
    with pytest.raises(IntegrityError) as error:
        db.commit()
    # y la app lo reconoce como "ya subiste este informe" (409), no como un error cualquiera
    assert modulo._es_informe_repetido(error.value)


@pytest.mark.skipif(
    not os.environ.get("PRUEBAS_DATABASE_URL"), reason="El bloqueo de fila solo existe en PostgreSQL"
)
def test_subidas_al_mismo_tiempo_no_se_saltan_el_tope(
    entrar, laboratorio, rubrica_lista, almacen, monkeypatch
):
    """El hallazgo alto: antes entraban 8 con tope de 5."""
    monkeypatch.setattr(modulo, "ENTREGAS_POR_HORA", 3)
    estudiante = entrar("estudiante")
    informes = [pdf(f"Versión {i} del informe del laboratorio.") for i in range(8)]

    def una(informe):
        with TestClient(app, client=("testclient", 50000)) as c:
            c.cookies.update(estudiante.cookies)
            return subir(c, laboratorio, informe=informe, enlace=REPO).status_code

    with ThreadPoolExecutor(max_workers=8) as hilos:
        codigos = list(hilos.map(una, informes))
    assert codigos.count(201) == 3, codigos
    assert set(codigos) <= {201, 429, 503}


# ---------- Límite por usuario y no por IP ----------


def test_la_clave_del_limite_es_el_usuario_y_no_la_ip(entrar):
    ana = entrar("estudiante", correo="ana@umanizales.edu.co")
    beto = entrar("estudiante", correo="beto@umanizales.edu.co")

    class Pedido:
        def __init__(self, cliente):
            self.cookies = dict(cliente.cookies)
            self.client = type("C", (), {"host": "10.0.0.1"})()  # la misma IP (el proxy de Render)

    clave_ana = seguridad.clave_de_usuario(Pedido(ana))
    clave_beto = seguridad.clave_de_usuario(Pedido(beto))
    assert clave_ana == f"usuario:{ana.usuario.id}"
    assert clave_ana != clave_beto


def test_sin_sesion_la_clave_es_la_ip():
    pedido = type("P", (), {"cookies": {}, "client": type("C", (), {"host": "10.0.0.1"})()})()
    assert seguridad.clave_de_usuario(pedido) == "ip:10.0.0.1"


# ---------- Auditoría sin repetir, listas, orden ----------


def test_el_mismo_intento_ajeno_no_se_repite_en_la_auditoria(entrar, laboratorio, rubrica_lista, almacen, db):
    ana = entrar("estudiante", correo="ana@umanizales.edu.co")
    entrega = subir(ana, laboratorio, enlace=REPO).json()
    beto = entrar("estudiante", correo="beto@umanizales.edu.co")
    for _ in range(5):
        beto.get(f"/api/entregas/{entrega['id']}")
    assert db.query(Auditoria).filter_by(accion="acceso_ajeno_denegado").count() == 1


def test_la_lista_de_estudiantes_se_pagina(entrar):
    for i in range(3):
        entrar("estudiante", correo=f"e{i}@umanizales.edu.co")
    docente = entrar("docente")
    assert len(docente.get("/api/estudiantes", params={"limite": 2}).json()) == 2
    assert len(docente.get("/api/estudiantes", params={"limite": 2, "desde": 2}).json()) == 1


def test_los_archivos_salen_en_orden_fijo(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio, codigo=zip_codigo(), imagenes=[png()], diapositivas=pptx())
    assert [e["tipo"] for e in r.json()["evidencias"]] == ["pdf", "codigo", "diapositivas", "imagen"]


def test_el_resumen_cuenta_solo_las_paginas_con_texto(entrar, laboratorio, rubrica_lista, almacen):
    informe = pdf(textos=["Informe del laboratorio con suficiente texto para leerlo.", ""])
    r = subir(entrar("estudiante"), laboratorio, informe=informe, enlace=REPO)
    assert r.status_code == 201, r.text
    assert r.json()["evidencias"][0]["resumen"] == "1 página con texto"


def test_un_portafolio_ajeno_que_no_existe_tampoco_revela_nada(entrar):
    r = entrar("estudiante").get(f"/api/portafolio/{uuid4()}")
    assert r.status_code == 404


# ---------- Tercera revisión: ZIP64, auditoría con tope, nombres ----------


def _zip64(archivos: dict[str, str]) -> bytes:
    """Un ZIP64 VÁLIDO (zipfile lo abre). Se arma bajando el umbral de zipfile para que
    escriba los registros ZIP64 aunque haya pocas entradas."""
    import io
    import zipfile
    from unittest import mock

    memoria = io.BytesIO()
    with mock.patch.object(zipfile, "ZIP_FILECOUNT_LIMIT", 1), zipfile.ZipFile(memoria, "w") as z:
        for ruta, datos in archivos.items():
            z.writestr(ruta, datos)
    contenido = memoria.getvalue()
    assert lector_zip._LOCALIZADOR_ZIP64 in contenido  # trae el localizador ZIP64
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:  # y zipfile lo abriría sin problema:
        assert len(z.infolist()) == len(archivos)  # la prueba solo pasa por la defensa
    return contenido


def test_un_zip64_se_rechaza_antes_de_abrirlo():
    with pytest.raises(ArchivoNoValido, match="No se pudo abrir"):
        lector_zip.leer_zip(_zip64({"a.py": "x = 1", "b.py": "y = 2", "c.py": "z = 3"}))


def test_un_pptx_zip64_se_rechaza():
    from app.archivos import diapositivas

    contenido = _zip64({"ppt/presentation.xml": "<p/>", "ppt/slides/slide1.xml": "<a:t>Hola</a:t>"})
    with pytest.raises(ArchivoNoValido, match="No se pudieron leer las diapositivas"):
        diapositivas.leer_diapositivas(contenido)


def test_un_word_zip64_se_rechaza_en_rubricas():
    from app.rubricas import extraer

    contenido = _zip64(
        {
            "[Content_Types].xml": "<Types/>",  # con una sola entrada zipfile no escribe ZIP64
            "word/document.xml": "<w:p><w:r><w:t>Criterio uno de la rúbrica</w:t></w:r></w:p>",
        }
    )
    with pytest.raises(ArchivoNoValido, match="Word"):
        extraer.extraer_texto(contenido)


def test_un_indice_que_no_cabe_antes_del_registro_final_se_rechaza():
    contenido = bytearray(zip_codigo())
    inicio = contenido.rfind(b"PK\x05\x06")
    contenido[inicio + 16 : inicio + 20] = (len(contenido)).to_bytes(4, "little")  # desplazamiento falso
    with pytest.raises(ArchivoNoValido, match="No se pudo abrir"):
        lector_zip.leer_zip(bytes(contenido))


def test_los_intentos_ajenos_tienen_tope_en_la_auditoria(entrar, db, monkeypatch):
    monkeypatch.setattr(modulo, "AJENOS_POR_HORA", 5)
    estudiante = entrar("estudiante")
    for _ in range(12):  # cada uno con un id distinto: el "no repetir" no alcanza
        assert estudiante.get(f"/api/portafolio/{uuid4()}").status_code == 404
    assert db.query(Auditoria).filter_by(accion="acceso_ajeno_denegado").count() == 5


@pytest.mark.parametrize(
    ("enviado", "visible"), [("<script>.pdf", "_script_.pdf"), ('a"b|c?.pdf', "a_b_c_.pdf")]
)
def test_el_nombre_visible_no_deja_pasar_etiquetas(enviado, visible):
    assert modulo.nombre_visible(enviado, "x") == visible


# ---------- Cuarta revisión: límite por ruta, nombres mal codificados, auditoría ----------


@pytest.mark.parametrize("ruta", ["/api/portafolio/{}", "/api/entregas/{}", "/api/evidencias/{}/enlace"])
def test_el_limite_por_minuto_cuenta_por_ruta_aunque_cambie_el_id(entrar, ruta):
    """Antes cada id tenía su propio contador: con ids al azar no había límite."""
    estudiante = entrar("estudiante")
    codigos = [estudiante.get(ruta.format(uuid4())).status_code for _ in range(61)]
    assert codigos[:60] == [404] * 60
    assert codigos[60] == 429


def _con_nombre_mal_codificado(contenido: bytes) -> bytes:
    """Cambia el "á" (bytes c3 a1) de un nombre interno marcado como UTF-8 por bytes inválidos."""
    a_tilde = "á".encode()  # b"\xc3\xa1"
    assert contenido.count(a_tilde) >= 1
    return contenido.replace(a_tilde, b"\xc3\x28")  # \xc3 sin su segundo byte: UTF-8 inválido


def test_un_zip_con_un_nombre_mal_codificado_da_aviso_y_cuenta_como_rechazo(
    entrar, laboratorio, rubrica_lista, almacen, db
):
    contenido = _con_nombre_mal_codificado(zip_codigo({"á.py": "x = 1"}))
    r = subir(entrar("estudiante"), laboratorio, codigo=contenido)
    assert r.status_code == 400
    assert r.json()["detail"] == "Código: No se pudo abrir el ZIP."
    assert db.query(Auditoria).filter_by(accion="archivo_rechazado").count() == 1


def test_un_pptx_con_un_nombre_mal_codificado_da_aviso():
    import io
    import zipfile

    from app.archivos import diapositivas

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
        z.writestr("ppt/media/á.png", "x")
    with pytest.raises(ArchivoNoValido, match="No se pudieron leer"):
        diapositivas.leer_diapositivas(_con_nombre_mal_codificado(memoria.getvalue()))


def test_un_word_con_un_nombre_mal_codificado_da_aviso():
    import io
    import zipfile

    from app.rubricas import extraer

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("word/document.xml", "<w:t>Criterio uno de la rúbrica</w:t>")
        z.writestr("word/media/á.png", "x")
    with pytest.raises(ArchivoNoValido, match="Word"):
        extraer.extraer_texto(_con_nombre_mal_codificado(memoria.getvalue()))


def test_al_llegar_al_tope_de_intentos_ajenos_queda_una_sola_fila_que_lo_dice(entrar, db, monkeypatch):
    monkeypatch.setattr(modulo, "AJENOS_POR_HORA", 3)
    estudiante = entrar("estudiante")
    for _ in range(8):
        estudiante.get(f"/api/portafolio/{uuid4()}")
    assert db.query(Auditoria).filter_by(accion="acceso_ajeno_denegado").count() == 3
    assert db.query(Auditoria).filter_by(accion="acceso_ajeno_tope").count() == 1


def test_el_mismo_enlace_no_se_anota_dos_veces_en_un_minuto(entrar, laboratorio, rubrica_lista, almacen, db):
    estudiante = entrar("estudiante")
    entrega = subir(estudiante, laboratorio, enlace=REPO).json()
    evidencia = entrega["evidencias"][0]["id"]
    for _ in range(4):
        assert estudiante.get(f"/api/evidencias/{evidencia}/enlace").status_code == 200
    assert db.query(Auditoria).filter_by(accion="enlace_emitido").count() == 1


@pytest.mark.parametrize(("enviado", "visible"), [("＜script＞.pdf", "_script_.pdf"), ("a／b.pdf", "b.pdf")])
def test_los_caracteres_de_ancho_completo_no_se_cuelan(enviado, visible):
    assert modulo.nombre_visible(enviado, "x") == visible


def test_otro_error_de_integridad_no_se_disfraza_de_informe_repetido(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    def falla(*_, **__):
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: entregas.sha256_informe"))

    monkeypatch.setattr(modulo, "registrar", falla)
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 500
    assert r.json()["detail"] == "Ocurrió un error. Intenta de nuevo."
    assert not any(p.is_file() for p in almacen.carpeta.rglob("*"))


def test_el_portafolio_tiene_orden_fijo_con_fechas_iguales(entrar, laboratorio, rubrica_lista, db):
    """Tres entregas con la misma fecha, guardadas con ids en orden ascendente: sin el
    desempate por id saldrían en el orden en que se guardaron, y la prueba fallaría siempre."""
    from datetime import UTC, datetime
    from uuid import UUID

    estudiante = entrar("estudiante")
    misma = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    ids = [UUID(int=i) for i in (1, 2, 3)]
    for i, entrega_id in enumerate(ids):
        db.add(
            Entrega(
                id=entrega_id,
                estudiante_id=estudiante.usuario.id,
                laboratorio_id=laboratorio.id,
                rubrica_version_id=rubrica_lista.id,
                sha256_informe=str(i) * 64,
                fecha=misma,
            )
        )
        db.commit()
    url = f"/api/portafolio/{estudiante.usuario.id}"
    entregas = estudiante.get(url).json()["cohortes"][0]["laboratorios"][0]["entregas"]
    assert [e["id"] for e in entregas] == [str(i) for i in reversed(ids)]


# ---------- Quinta revisión: desplazamiento enorme, NFKC en rutas, tope de enlaces ----------


def _con_desplazamiento_enorme(contenido: bytes) -> bytes:
    """Pone en el índice un campo extra ZIP64 con desplazamiento 2^63+5: zipfile lanzaba
    OverflowError al abrir la entrada (500), y no cuenta como ZIP64 para revisar_indice."""
    import struct

    datos = bytearray(contenido)
    i = datos.find(b"PK\x01\x02")
    largo_nombre, largo_extra, _ = struct.unpack("<HHH", datos[i + 28 : i + 34])
    datos[i + 42 : i + 46] = b"\xff\xff\xff\xff"  # el desplazamiento "está en el extra"
    extra = struct.pack("<HHQ", 1, 8, 2**63 + 5)
    datos[i + 30 : i + 32] = struct.pack("<H", largo_extra + len(extra))
    fin_nombre = i + 46 + largo_nombre
    datos[fin_nombre:fin_nombre] = extra
    # el índice creció: se corrige su tamaño en el registro final
    fin = datos.rfind(b"PK\x05\x06")
    peso = struct.unpack("<I", datos[fin + 12 : fin + 16])[0]
    datos[fin + 12 : fin + 16] = struct.pack("<I", peso + len(extra))
    return bytes(datos)


def test_un_zip_con_desplazamiento_enorme_da_aviso_y_cuenta_como_rechazo(
    entrar, laboratorio, rubrica_lista, almacen, db
):
    contenido = _con_desplazamiento_enorme(zip_codigo({"a.py": "x = 1"}))
    r = subir(entrar("estudiante"), laboratorio, codigo=contenido)
    assert r.status_code == 400
    assert r.json()["detail"] == "Código: No se pudo abrir el ZIP."
    assert db.query(Auditoria).filter_by(accion="archivo_rechazado").count() == 1


def test_un_pptx_y_un_word_con_desplazamiento_enorme_dan_aviso():
    import io
    import zipfile

    from app.archivos import diapositivas
    from app.rubricas import extraer

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
    with pytest.raises(ArchivoNoValido, match="No se pudieron leer"):
        diapositivas.leer_diapositivas(_con_desplazamiento_enorme(memoria.getvalue()))

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("word/document.xml", "<w:t>Criterio uno de la rúbrica</w:t>")
    with pytest.raises(ArchivoNoValido, match="Word"):
        extraer.extraer_texto(_con_desplazamiento_enorme(memoria.getvalue()))


@pytest.mark.parametrize("ruta", ["src/＜entrega＞.py", "a/．．/b.py", "＂x＂.py"])
def test_un_zip_con_rutas_de_ancho_completo_se_rechaza(ruta):
    with pytest.raises(ArchivoNoValido, match="no se permiten"):
        lector_zip.leer_zip(zip_codigo({ruta: "x"}))


def test_un_zip_de_mac_con_tildes_descompuestas_si_pasa():
    import unicodedata

    ruta = unicodedata.normalize("NFD", "módulo.py")  # "o" + tilde, como los guarda macOS
    assert ruta != "módulo.py"
    resultado = lector_zip.leer_zip(zip_codigo({ruta: "x = 1\n"}))
    assert len(resultado.archivos) == 1


def test_los_enlaces_tienen_tope_por_hora_en_la_auditoria(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    monkeypatch.setattr(modulo, "ENLACES_POR_HORA", 2)
    estudiante = entrar("estudiante")
    entrega = subir(estudiante, laboratorio, codigo=zip_codigo(), imagenes=[png(), png()]).json()
    for evidencia in entrega["evidencias"]:  # 4 archivos distintos
        assert estudiante.get(f"/api/evidencias/{evidencia['id']}/enlace").status_code == 200
    assert db.query(Auditoria).filter_by(accion="enlace_emitido").count() == 2


# ---------- Sexta revisión: nombres comunes, tope de enlaces con rastro, rama 409 ----------


@pytest.mark.parametrize(
    ("ruta", "guardada"),
    [
        ("Taller 1º.py", "Taller 1o.py"),
        ("2ª_parte/a.py", "2a_parte/a.py"),
        ("x².py", "x2.py"),
        ("ｍain.py", "main.py"),
        ("Captura a. m.py", "Captura a. m.py"),
    ],
)
def test_los_nombres_comunes_con_simbolos_pasan_normalizados(ruta, guardada):
    """Rechazar todo lo que cambiara con NFKC dejaba fuera nombres normales (6.ª revisión)."""
    resultado = lector_zip.leer_zip(zip_codigo({ruta: "x = 1\n"}))
    assert [a.ruta for a in resultado.archivos] == [guardada]
    assert resultado.arbol == [guardada]


def test_el_aviso_de_rutas_no_repite_lo_que_mando_el_estudiante():
    with pytest.raises(ArchivoNoValido) as error:
        lector_zip.leer_zip(zip_codigo({"../secreto-del-estudiante.py": "x"}))
    assert "secreto-del-estudiante" not in str(error.value)
    assert str(error.value) == lector_zip.RUTA_NO_PERMITIDA


def test_pasado_el_tope_de_enlaces_queda_rastro(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch, caplog
):
    import logging

    monkeypatch.setattr(modulo, "ENLACES_POR_HORA", 1)
    estudiante = entrar("estudiante")
    entrega = subir(estudiante, laboratorio, codigo=zip_codigo(), imagenes=[png(), png()]).json()
    with caplog.at_level(logging.WARNING, logger="asesor.entregas"):
        for evidencia in entrega["evidencias"]:  # 4 archivos: 1 anotado y 3 por encima del tope
            assert estudiante.get(f"/api/evidencias/{evidencia['id']}/enlace").status_code == 200
    assert db.query(Auditoria).filter_by(accion="enlace_emitido").count() == 1
    assert db.query(Auditoria).filter_by(accion="enlace_tope").count() == 1  # una sola fila por hora
    avisos = [r for r in caplog.records if "Enlace por encima del tope" in r.getMessage()]
    assert len(avisos) == 3
    assert all(r.levelno == logging.WARNING for r in avisos)


def test_la_restriccion_unica_responde_409_por_la_ruta(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    """La rama del IntegrityError de verdad: se apaga la revisión previa para que el mismo
    informe llegue hasta la base (como dos subidas al mismo tiempo)."""
    monkeypatch.setattr(modulo, "_revisar_topes", lambda *a, **k: None)
    estudiante = entrar("estudiante")
    informe = pdf()
    assert subir(estudiante, laboratorio, informe=informe, enlace=REPO).status_code == 201
    archivos_antes = {p for p in almacen.carpeta.rglob("*") if p.is_file()}
    r = subir(estudiante, laboratorio, informe=informe, enlace=REPO)
    assert r.status_code == 409
    assert r.json()["detail"] == modulo.REPETIDA
    assert {p for p in almacen.carpeta.rglob("*") if p.is_file()} == archivos_antes  # se borró lo nuevo
    assert db.query(Entrega).count() == 1


# ---------- Séptima revisión: red de seguridad con rastro, nombres repetidos ----------


class _ErrorNuestro(Exception):
    """Un error que no es de ningún tipo conocido, como uno de programación en el lector."""


def _abrir_falla(*_, **__):
    raise _ErrorNuestro("falla simulada")


def test_la_red_de_seguridad_deja_rastro_en_los_tres_lectores(monkeypatch, caplog):
    import io
    import logging
    import zipfile

    from app.archivos import diapositivas
    from app.rubricas import extraer

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
        z.writestr("ppt/slides/slide1.xml", "<a:t>Hola</a:t>")
    pptx_falso = memoria.getvalue()
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("word/document.xml", "<w:t>Criterio uno de la rúbrica</w:t>")
    docx_falso = memoria.getvalue()
    codigo = zip_codigo({"a.py": "x = 1"})

    monkeypatch.setattr(zipfile.ZipFile, "open", _abrir_falla)
    with caplog.at_level(logging.WARNING, logger="asesor.archivos"):
        with pytest.raises(ArchivoNoValido, match="No se pudo abrir el ZIP"):
            lector_zip.leer_zip(codigo)
        with pytest.raises(ArchivoNoValido, match="No se pudieron leer"):
            diapositivas.leer_diapositivas(pptx_falso)
        with pytest.raises(ArchivoNoValido, match="Word"):
            extraer.extraer_texto(docx_falso)
    avisos = [r.getMessage() for r in caplog.records if "Error inesperado" in r.getMessage()]
    assert len(avisos) == 3
    assert all("_ErrorNuestro" in a and "falla simulada" not in a for a in avisos)  # solo el tipo


def test_los_errores_conocidos_no_llenan_el_registro(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="asesor.archivos"), pytest.raises(ArchivoNoValido):
        lector_zip.leer_zip(b"PK\x03\x04" + b"basura" * 50)
    assert not [r for r in caplog.records if "Error inesperado" in r.getMessage()]


@pytest.mark.parametrize(
    "archivos",
    [
        {"main.py": "a", "ｍａｉｎ.py": "b"},
        {"main.py": "a", "MAIN.py": "b"},
        {"src/a.py": "a", "src/A.py": "b"},
        {"Src/a.py": "a", "src/a.py": "b"},
    ],
)
def test_un_zip_con_dos_archivos_del_mismo_nombre_se_rechaza(archivos):
    with pytest.raises(ArchivoNoValido) as error:
        lector_zip.leer_zip(zip_codigo(archivos))
    assert str(error.value) == lector_zip.RUTA_REPETIDA


def test_un_zip_con_la_misma_entrada_dos_veces_se_rechaza():
    import io
    import warnings
    import zipfile

    memoria = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(memoria, "w") as z:
        warnings.simplefilter("ignore")  # zipfile avisa "Duplicate name": es justo lo que se prueba
        z.writestr("main.py", "print('uno')")
        z.writestr("main.py", "print('dos')")
    with pytest.raises(ArchivoNoValido) as error:
        lector_zip.leer_zip(memoria.getvalue())
    assert str(error.value) == lector_zip.RUTA_REPETIDA


def test_carpetas_y_archivos_distintos_si_pasan():
    resultado = lector_zip.leer_zip(zip_codigo({"src/a.py": "a", "src/b.py": "b", "tests/a.py": "c"}))
    assert len(resultado.archivos) == 3


@pytest.mark.parametrize(
    "archivos",
    [
        {"main.py": "a", "./main.py": "b"},
        {"a/main.py": "a", "a//main.py": "b"},
        {"a/main.py": "a", "a/./main.py": "b"},
        {"main.py": "a", "main.py ": "b"},
        {" main.py": "a"},
        {"carpeta /a.py": "a"},
    ],
)
def test_rutas_con_tramos_vacios_puntos_o_espacios_se_rechazan(archivos):
    """Pasada final: 'main.py' y './main.py' llegaban al evaluador como dos archivos."""
    with pytest.raises(ArchivoNoValido) as error:
        lector_zip.leer_zip(zip_codigo(archivos))
    assert str(error.value) == lector_zip.RUTA_NO_PERMITIDA


def test_las_carpetas_con_barra_final_siguen_pasando():
    import io
    import zipfile

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("src/", "")  # entrada de carpeta
        z.writestr("src/a.py", "x = 1")
    assert [a.ruta for a in lector_zip.leer_zip(memoria.getvalue()).archivos] == ["src/a.py"]
