"""La traza guarda el cambio de nivel con el valor anterior y el nuevo (RF-15, RNF-08)."""

from test_revision import sembrar


def test_el_cambio_de_nivel_queda_en_la_traza(db, laboratorio, rubrica_lista, crear_usuario, entrar):
    estudiante = crear_usuario("estudiante", correo="est.traza@umanizales.edu.co")
    docente = entrar("docente", correo="docente.traza@umanizales.edu.co")
    admin = entrar("administrador", correo="admin.traza@umanizales.edu.co")
    evaluacion = sembrar(db, laboratorio, rubrica_lista, estudiante, docente.usuario.id)

    ajuste = docente.post(
        f"/api/evaluaciones/{evaluacion.id}/ajustes",
        json={"criterio_id": "c1", "nivel_id": "bajo", "justificacion": "No cubre los errores."},
    )
    assert ajuste.status_code == 200, ajuste.text

    traza = docente.get(f"/api/evaluaciones/{evaluacion.id}/traza")
    assert traza.status_code == 200, traza.text
    cuerpo = traza.json()
    assert cuerpo["rubrica_version_id"] == str(rubrica_lista.id)
    assert cuerpo["modelo"] == "modelo-prueba"
    assert cuerpo["version_prompt"] == "evaluar_criterio_v2"
    assert cuerpo["evidencias"][0]["sha256"] == "ab" * 32
    assert cuerpo["verificaciones"][0]["tipo"] == "sintaxis"
    assert "nota_final" not in cuerpo
    cambio = cuerpo["revisiones"][0]
    assert cambio["accion"] == "ajustar_nivel"
    assert cambio["valor_anterior"] == "alto"
    assert cambio["valor_nuevo"] == "bajo"
    assert cambio["justificacion"] == "No cubre los errores."
    assert cambio["docente_id"] == str(docente.usuario.id)

    registros = admin.get("/api/auditoria").json()
    assert any(r["accion"] == "ajustar_nivel" and r["entidad_id"] == str(evaluacion.id) for r in registros)
    assert (
        entrar("estudiante", correo="est.traza2@umanizales.edu.co")
        .get(f"/api/evaluaciones/{evaluacion.id}/traza")
        .status_code
        == 403
    )
