"""Traza de cada evaluación (RF-15, RNF-08; fila C6 de la matriz del SRS; D-21).

La prueba de la matriz: un cambio de nivel queda auditado con el valor anterior y el nuevo.
"""

from test_revision import _publicar, ajustar

from app.modelos import Auditoria


def test_un_cambio_de_nivel_queda_auditado(evaluada, db):  # noqa: F811
    """La prueba de la matriz (C6)."""
    docente, evaluacion = evaluada
    ajustar(docente, evaluacion, "c1", "bajo", "El informe no muestra pruebas.")
    fila = db.query(Auditoria).filter_by(accion="evaluacion_ajustada").one()
    assert fila.usuario_id == docente.usuario.id
    assert fila.entidad_id == evaluacion["id"]
    assert fila.detalle == {"criterio_id": "c1", "anterior": "alto", "nuevo": "bajo"}


def test_la_traza_tiene_todo_lo_que_pide_rnf_08(evaluada, entrar):  # noqa: F811
    docente, evaluacion = evaluada
    ajustar(docente, evaluacion, "c1", "bajo", "El informe no muestra pruebas.")
    _publicar(docente, evaluacion)
    r = docente.get(f"/api/evaluaciones/{evaluacion['id']}/traza")
    assert r.status_code == 200, r.text
    traza = r.json()
    assert traza["rubrica_version_id"] == evaluacion["rubrica_version_id"]
    assert (traza["proveedor"], traza["modelo"], traza["version_prompt"]) == (
        "openai",
        "modelo-prueba",
        "evaluar_criterio_v2",
    )
    assert traza["evidencias"] and all(len(e["sha256"]) == 64 for e in traza["evidencias"])
    assert traza["verificaciones"]  # lo que dijo el sandbox
    assert (traza["tokens_entrada"], traza["tokens_salida"]) == (3000, 600)
    assert traza["aprobada_por"] == str(docente.usuario.id)
    assert traza["fecha_aprobacion"] and traza["fecha_publicacion"]
    acciones = [
        (r["accion"], r["criterio_id"], r["valor_anterior"], r["valor_nuevo"]) for r in traza["revisiones"]
    ]
    assert acciones == [
        ("ajustar_nivel", "c1", "alto", "bajo"),
        ("aprobar", None, None, "3.7"),
        ("publicar", None, None, None),
    ]
    assert traza["revisiones"][0]["justificacion"] == "El informe no muestra pruebas."
    # El administrador también la ve; el estudiante no
    assert entrar("administrador").get(f"/api/evaluaciones/{evaluacion['id']}/traza").status_code == 200
    otro = entrar("estudiante", correo="otro.estudiante@umanizales.edu.co")
    assert otro.get(f"/api/evaluaciones/{evaluacion['id']}/traza").status_code == 403


def test_aprobar_y_publicar_quedan_en_la_auditoria(evaluada, db):  # noqa: F811
    docente, evaluacion = evaluada
    _publicar(docente, evaluacion)
    acciones = {a.accion for a in db.query(Auditoria).filter_by(entidad_id=evaluacion["id"]).all()}
    assert {"evaluacion_aprobada", "evaluacion_publicada"} <= acciones
