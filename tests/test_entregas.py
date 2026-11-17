"""Subir entregas, verlas y bajar sus archivos (RF-07, RF-09, RNF-07; fila F1 de la matriz)."""

import hashlib
from uuid import UUID, uuid4

import pytest
from archivos_prueba import TEXTO_INFORME, pdf, png, pptx, zip_codigo

from app.api import entregas as modulo
from app.modelos import Auditoria, Evidencia

REPO = "https://github.com/ana/agente-archivos"


def subir(cliente, laboratorio, *, informe=None, codigo=None, enlace=None, imagenes=(), diapositivas=None):
    archivos = [("informe", ("informe.pdf", pdf() if informe is None else informe, "application/pdf"))]
    if codigo is not None:
        archivos.append(("codigo", ("codigo.zip", codigo, "application/zip")))
    for i, imagen in enumerate(imagenes):
        archivos.append(("imagenes", (f"foto{i}.png", imagen, "image/png")))
    if diapositivas is not None:
        archivos.append(("diapositivas", ("expo.pptx", diapositivas, "application/octet-stream")))
    datos = {"laboratorio_id": str(laboratorio.id)}
    if enlace is not None:
        datos["enlace_github"] = enlace
    return cliente.post("/api/entregas", data=datos, files=archivos)


# ---------- Subir ----------


def test_un_pdf_con_texto_y_un_zip_quedan_con_su_huella(entrar, laboratorio, rubrica_lista, almacen, db):
    """La prueba de CU-03: quedan en el portafolio con su SHA-256."""
    estudiante = entrar("estudiante")
    informe, codigo = pdf(), zip_codigo()
    r = subir(estudiante, laboratorio, informe=informe, codigo=codigo)
    assert r.status_code == 201, r.text
    entrega = r.json()
    assert entrega["rubrica_version_id"] == str(rubrica_lista.id)
    assert entrega["rubrica_version_numero"] == 1
    por_tipo = {e["tipo"]: e for e in entrega["evidencias"]}
    assert por_tipo["pdf"]["sha256"] == hashlib.sha256(informe).hexdigest()
    assert por_tipo["codigo"]["sha256"] == hashlib.sha256(codigo).hexdigest()
    assert por_tipo["pdf"]["resumen"] == "1 página con texto"
    assert por_tipo["codigo"]["resumen"] == "2 archivos de código, 1 omitido"

    # El archivo quedó guardado tal cual y el texto se extrajo (RF-09)
    fila = db.get(Evidencia, UUID(por_tipo["pdf"]["id"]))
    assert almacen.leer(fila.ruta_storage) == informe
    assert TEXTO_INFORME in fila.texto_extraido["paginas"][0]
    codigo_fila = db.get(Evidencia, UUID(por_tipo["codigo"]["id"]))
    assert codigo_fila.texto_extraido["arbol"] == ["agente/README.md", "agente/logo.png", "agente/main.py"]


def test_la_entrega_queda_en_la_auditoria_con_las_huellas_y_sin_contenido(
    entrar, laboratorio, rubrica_lista, almacen, db
):
    subir(entrar("estudiante"), laboratorio, codigo=zip_codigo())
    fila = db.query(Auditoria).filter_by(accion="entrega_subida").one()
    assert {a["tipo"] for a in fila.detalle["archivos"]} == {"pdf", "codigo"}
    assert all(len(a["sha256"]) == 64 for a in fila.detalle["archivos"])
    assert TEXTO_INFORME not in str(fila.detalle)


def test_un_pdf_escaneado_se_rechaza_con_un_aviso(entrar, laboratorio, rubrica_lista, almacen):
    """La prueba de la matriz (F1)."""
    r = subir(entrar("estudiante"), laboratorio, informe=pdf(texto=None), enlace=REPO)
    assert r.status_code == 400
    assert "no tiene texto legible" in r.json()["detail"]


def test_con_enlace_de_github_y_sin_zip_tambien_sirve(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 201, r.text
    assert r.json()["enlace_github"] == REPO


def test_sin_zip_ni_enlace_falta_el_codigo(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio)
    assert r.status_code == 422
    assert r.json()["detail"] == modulo.FALTA_CODIGO


@pytest.mark.parametrize(
    "enlace", ["https://gitlab.com/ana/lab", "http://github.com/ana/lab", "github.com/ana"]
)
def test_un_enlace_que_no_es_de_github_se_rechaza(entrar, laboratorio, rubrica_lista, almacen, enlace):
    r = subir(entrar("estudiante"), laboratorio, enlace=enlace)
    assert r.status_code == 422
    assert r.json()["detail"] == modulo.ENLACE_MALO


def test_imagenes_y_diapositivas_opcionales(entrar, laboratorio, rubrica_lista, almacen, db):
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO, imagenes=[png(), png()], diapositivas=pptx())
    assert r.status_code == 201, r.text
    tipos = sorted(e["tipo"] for e in r.json()["evidencias"])
    assert tipos == ["diapositivas", "imagen", "imagen", "pdf"]
    diapos = next(e for e in r.json()["evidencias"] if e["tipo"] == "diapositivas")
    assert diapos["resumen"] == "2 diapositivas con texto"
    fila = db.get(Evidencia, UUID(diapos["id"]))
    assert fila.texto_extraido["paginas"] == ["Diapositiva uno: el agente", "Diapositiva dos: resultados"]


def test_mas_de_cinco_imagenes_se_rechaza(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO, imagenes=[png()] * 6)
    assert r.status_code == 422


def test_una_imagen_que_no_es_imagen_se_rechaza(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO, imagenes=[b"<script>alert(1)</script>"])
    assert r.status_code == 400
    assert "PNG, JPG o WEBP" in r.json()["detail"]


def test_un_informe_que_no_es_pdf_se_rechaza_aunque_se_llame_pdf(entrar, laboratorio, rubrica_lista, almacen):
    r = subir(entrar("estudiante"), laboratorio, informe=zip_codigo(), enlace=REPO)
    assert r.status_code == 400
    assert r.json()["detail"] == "Informe: debe ser un PDF."


def test_un_zip_peligroso_se_rechaza_y_no_queda_nada_guardado(
    entrar, laboratorio, rubrica_lista, almacen, db
):
    r = subir(entrar("estudiante"), laboratorio, codigo=zip_codigo({"../../fuera.py": "x"}))
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Código:")
    assert db.query(Evidencia).count() == 0
    assert not any(p.is_file() for p in almacen.carpeta.rglob("*"))


def test_un_informe_muy_grande_se_rechaza(entrar, laboratorio, rubrica_lista, almacen, monkeypatch):
    monkeypatch.setattr(modulo, "MAXIMO_INFORME", 100)  # el PDF de prueba pesa menos de 1 KB
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 413
    assert "Informe" in r.json()["detail"]


def test_la_peticion_de_mas_de_30_mb_se_frena_antes_de_leerla(cliente, laboratorio):
    r = cliente.post(
        "/api/entregas",
        data={"laboratorio_id": str(laboratorio.id)},
        files={"informe": ("i.pdf", b"a" * (31 * 1024 * 1024))},
    )
    assert r.status_code == 413


def test_sin_rubrica_lista_no_se_puede_entregar(entrar, laboratorio, almacen):
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 409
    assert r.json()["detail"] == modulo.SIN_RUBRICA


def test_laboratorio_que_no_existe_da_404(entrar, rubrica_lista, almacen):
    class Falso:
        id = uuid4()

    assert subir(entrar("estudiante"), Falso, enlace=REPO).status_code == 404


def test_el_docente_no_sube_entregas(entrar, laboratorio, rubrica_lista, almacen):
    assert subir(entrar("docente"), laboratorio, enlace=REPO).status_code == 403


def test_se_puede_entregar_varias_veces_y_nada_se_borra(entrar, laboratorio, rubrica_lista, almacen):
    estudiante = entrar("estudiante")
    primera = subir(estudiante, laboratorio, enlace=REPO).json()
    segunda = subir(estudiante, laboratorio, enlace=REPO).json()
    ids = [e["id"] for e in estudiante.get("/api/mis-entregas").json()]
    assert ids == [segunda["id"], primera["id"]]


def test_si_el_almacen_falla_no_queda_la_entrega(
    entrar, laboratorio, rubrica_lista, almacen, db, monkeypatch
):
    from app.almacen import AlmacenNoDisponible

    def falla(*_):
        raise AlmacenNoDisponible("sin almacén")

    monkeypatch.setattr(almacen, "guardar", falla)
    r = subir(entrar("estudiante"), laboratorio, enlace=REPO)
    assert r.status_code == 503
    assert db.query(Evidencia).count() == 0


def test_el_nombre_del_archivo_no_decide_donde_se_guarda(entrar, laboratorio, rubrica_lista, almacen, db):
    r = entrar("estudiante").post(
        "/api/entregas",
        data={"laboratorio_id": str(laboratorio.id), "enlace_github": REPO},
        files={"informe": ("../../..\\C:\\informe\x00.pdf", pdf(), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    evidencia = r.json()["evidencias"][0]
    assert not any(c in evidencia["nombre"] for c in "/\\:\x00")
    assert evidencia["nombre"].endswith(".pdf")
    fila = db.get(Evidencia, UUID(evidencia["id"]))
    assert fila.ruta_storage == f"entregas/{r.json()['id']}/{evidencia['id']}"


@pytest.mark.parametrize(
    ("enviado", "visible"),
    [
        ("../../..\\C:\\informe\x00.pdf", "informe.pdf"),
        ("carpeta/mi informe final.pdf", "mi informe final.pdf"),
        ("  .oculto.pdf ", "oculto.pdf"),
        ("", "defecto.pdf"),
        (None, "defecto.pdf"),
    ],
)
def test_el_nombre_visible_se_limpia(enviado, visible):
    assert modulo.nombre_visible(enviado, "defecto.pdf") == visible


def test_el_nombre_visible_no_pasa_de_120_caracteres():
    assert len(modulo.nombre_visible("a" * 300 + ".pdf", "x")) == 120


# ---------- Ver ----------


def test_el_estudiante_no_ve_la_entrega_de_otro(entrar, laboratorio, rubrica_lista, almacen):
    ana = entrar("estudiante", correo="ana@umanizales.edu.co")
    entrega = subir(ana, laboratorio, enlace=REPO).json()
    beto = entrar("estudiante", correo="beto@umanizales.edu.co")
    assert beto.get(f"/api/entregas/{entrega['id']}").status_code == 404
    assert beto.get("/api/mis-entregas").json() == []
    evidencia = entrega["evidencias"][0]["id"]
    assert beto.get(f"/api/evidencias/{evidencia}/enlace").status_code == 404


def test_el_docente_ve_las_entregas_del_laboratorio(entrar, laboratorio, rubrica_lista, almacen):
    subir(entrar("estudiante", correo="ana@umanizales.edu.co"), laboratorio, enlace=REPO)
    subir(entrar("estudiante", correo="beto@umanizales.edu.co"), laboratorio, enlace=REPO)
    docente = entrar("docente")
    lista = docente.get(f"/api/laboratorios/{laboratorio.id}/entregas").json()
    assert len(lista) == 2
    assert docente.get(f"/api/entregas/{lista[0]['id']}").status_code == 200


def test_entrega_que_no_existe_da_404(entrar):
    assert entrar("docente").get(f"/api/entregas/{uuid4()}").status_code == 404


# ---------- Bajar (RNF-07) ----------


def test_se_baja_con_el_enlace_firmado_y_sin_el_no(entrar, laboratorio, rubrica_lista, almacen, cliente):
    estudiante = entrar("estudiante")
    informe = pdf()
    entrega = subir(estudiante, laboratorio, informe=informe, enlace=REPO).json()
    evidencia = entrega["evidencias"][0]["id"]

    enlace = estudiante.get(f"/api/evidencias/{evidencia}/enlace").json()
    assert enlace["vence_en_seg"] == 300
    # Cualquiera con el enlace lo baja mientras no venza (como en Supabase), sin sesión
    r = cliente.get(enlace["url"])
    assert r.status_code == 200
    assert r.content == informe
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")

    # Sin enlace, o con uno inventado, no hay archivo
    assert cliente.get(f"/api/evidencias/{evidencia}/enlace").status_code == 401
    assert cliente.get("/api/archivos/token-inventado").status_code == 404


def test_el_docente_tambien_pide_el_enlace(entrar, laboratorio, rubrica_lista, almacen):
    entrega = subir(entrar("estudiante"), laboratorio, enlace=REPO).json()
    r = entrar("docente").get(f"/api/evidencias/{entrega['evidencias'][0]['id']}/enlace")
    assert r.status_code == 200
