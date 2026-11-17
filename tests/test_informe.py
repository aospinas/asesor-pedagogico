"""Informe integrado de las dos cohortes y su PDF (RF-16)."""

from test_revision import sembrar

from app.modelos import Cohorte, Laboratorio


def _laboratorio(db, nombre_cohorte, titulo, temas):
    cohorte = Cohorte(nombre=nombre_cohorte, periodo="2026-2")
    db.add(cohorte)
    db.flush()
    laboratorio = Laboratorio(
        cohorte_id=cohorte.id,
        titulo=titulo,
        descripcion="Práctica",
        objetivos="Aplicar el tema",
        temas_ia=temas,
    )
    db.add(laboratorio)
    db.commit()
    return laboratorio


def _publicar(db, docente, laboratorio, rubrica, estudiante):
    evaluacion = sembrar(db, laboratorio, rubrica, estudiante, docente.usuario.id)
    assert docente.post(f"/api/evaluaciones/{evaluacion.id}/aprobar").status_code == 200
    assert docente.post(f"/api/evaluaciones/{evaluacion.id}/publicar").status_code == 200
    return evaluacion


def test_el_informe_reune_las_dos_cohortes_y_el_pdf_las_nombra(
    db, rubrica_lista, crear_usuario, entrar, laboratorio
):
    # La rúbrica de la prueba pertenece a `laboratorio` (cohorte 1). La segunda cohorte
    # necesita su propia versión: se reutiliza la misma estructura guardándola ahí.
    from datos_prueba import rubrica_de_prueba

    from app.esquemas import RubricaEstructura
    from app.rubricas import versiones

    docente = entrar("docente", correo="docente.inf@umanizales.edu.co")
    estudiante = crear_usuario("estudiante", correo="est.inf@umanizales.edu.co")
    segunda = _laboratorio(db, "Cohorte 2", "Laboratorio de prompting", ["prompting"])
    version2 = versiones.guardar_version(
        db,
        segunda.id,
        RubricaEstructura.model_validate(rubrica_de_prueba()),
        origen="editor",
        creada_por=docente.usuario.id,
    )
    db.commit()
    _publicar(db, docente, laboratorio, rubrica_lista, estudiante)
    _publicar(db, docente, segunda, version2, estudiante)

    r = docente.get(f"/api/informe/{estudiante.id}")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {lab["cohorte"].split(" · ")[0] for lab in cuerpo["laboratorios"]} == {"Cohorte 1", "Cohorte 2"}
    assert cuerpo["promedio_general"] == 5.0
    assert any(t["tema"] == "agentes" for t in cuerpo["temas"])
    assert any(t["tema"] == "prompting" for t in cuerpo["temas"])

    pdf = docente.get(f"/api/informe/{estudiante.id}/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    import pymupdf

    documento = pymupdf.open(stream=pdf.content, filetype="pdf")
    texto = "".join(pagina.get_text() for pagina in documento)
    documento.close()
    assert "Cohorte 1" in texto
    assert "Cohorte 2" in texto
    assert "Laboratorio de prompting" in texto


def test_otro_estudiante_no_ve_el_informe(db, laboratorio, rubrica_lista, crear_usuario, entrar):
    docente = entrar("docente", correo="docente.inf2@umanizales.edu.co")
    estudiante = crear_usuario("estudiante", correo="est.inf2@umanizales.edu.co")
    ajeno = entrar("estudiante", correo="ajeno.inf@umanizales.edu.co")
    _publicar(db, docente, laboratorio, rubrica_lista, estudiante)
    assert ajeno.get(f"/api/informe/{estudiante.id}").status_code == 404
    assert ajeno.get(f"/api/mapa/{estudiante.id}").status_code == 404
