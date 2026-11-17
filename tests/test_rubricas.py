"""Validación y versiones de la rúbrica (RF-05, RF-06; fila F3 de la matriz del SRS)."""

from uuid import UUID, uuid4

import pytest

from app.modelos import Auditoria, RubricaVersion
from app.rubricas import versiones


def _url(lab) -> str:
    return f"/api/laboratorios/{lab.id}/rubrica"


def test_pesos_que_suman_90_quedan_bloqueados(entrar, laboratorio, rubrica_de_prueba):
    """La prueba que pide la matriz: la rúbrica se guarda, pero no sirve para evaluar."""
    docente = entrar("docente")
    r = docente.put(_url(laboratorio), json=rubrica_de_prueba(pesos=(40, 30, 20)))
    assert r.status_code == 201, r.text
    version = r.json()
    assert version["valida"] is False
    assert "Los pesos suman 90 %, deben sumar 100 %." in version["errores"]


def test_la_rubrica_invalida_no_se_puede_evaluar(entrar, laboratorio, db, rubrica_de_prueba):
    entrar("docente").put(_url(laboratorio), json=rubrica_de_prueba(pesos=(40, 30, 20)))
    with pytest.raises(versiones.RubricaNoEvaluable, match="errores"):
        versiones.version_evaluable(db, laboratorio.id)


def test_sin_rubrica_no_se_puede_evaluar(db, laboratorio):
    with pytest.raises(versiones.RubricaNoEvaluable, match="no tiene rúbrica"):
        versiones.version_evaluable(db, laboratorio.id)


def test_corregir_crea_una_version_nueva_y_la_vieja_no_cambia(entrar, laboratorio, db, rubrica_de_prueba):
    docente = entrar("docente")
    v1 = docente.put(_url(laboratorio), json=rubrica_de_prueba(pesos=(40, 30, 20))).json()
    v2 = docente.put(_url(laboratorio), json=rubrica_de_prueba()).json()

    assert (v1["numero"], v2["numero"]) == (1, 2)
    assert v2["valida"] is True and v2["errores"] == []
    assert v2["origen"] == "editor"

    vieja = db.get(RubricaVersion, UUID(v1["id"]))
    assert vieja.valida is False
    assert [c["peso"] for c in vieja.estructura["criterios"]] == [40, 30, 20]

    vigente = docente.get(_url(laboratorio)).json()
    assert vigente["id"] == v2["id"]
    assert str(versiones.version_evaluable(db, laboratorio.id).id) == v2["id"]


def test_las_versiones_se_listan_de_la_mas_nueva_a_la_mas_vieja(entrar, laboratorio, rubrica_de_prueba):
    docente = entrar("docente")
    for _ in range(3):
        docente.put(_url(laboratorio), json=rubrica_de_prueba())
    numeros = [v["numero"] for v in docente.get(_url(laboratorio) + "/versiones").json()]
    assert numeros == [3, 2, 1]


def test_cada_version_queda_en_la_auditoria(entrar, laboratorio, db, rubrica_de_prueba):
    docente = entrar("docente")
    docente.put(_url(laboratorio), json=rubrica_de_prueba(pesos=(40, 30, 20)))
    fila = db.query(Auditoria).filter_by(accion="rubrica_corregida").one()
    assert fila.usuario_id == docente.usuario.id
    assert fila.detalle["numero"] == 1
    assert fila.detalle["valida"] is False


def test_el_estudiante_ve_la_rubrica_valida(entrar, laboratorio, rubrica_de_prueba):
    entrar("docente").put(_url(laboratorio), json=rubrica_de_prueba())
    r = entrar("estudiante").get(_url(laboratorio))
    assert r.status_code == 200
    # Solo la estructura: sin errores, sin quién la hizo ni de dónde salió
    assert set(r.json()) == {"numero", "estructura", "fecha"}


def test_el_estudiante_no_ve_un_borrador_con_errores(entrar, laboratorio, rubrica_de_prueba):
    docente = entrar("docente")
    docente.put(_url(laboratorio), json=rubrica_de_prueba())
    docente.put(_url(laboratorio), json=rubrica_de_prueba(pesos=(50, 50, 50)))
    r = entrar("estudiante").get(_url(laboratorio))
    # Ve la última versión válida, no el borrador
    assert r.status_code == 200
    assert r.json()["numero"] == 1


def test_el_estudiante_no_ve_nada_si_nunca_hubo_una_valida(entrar, laboratorio, rubrica_de_prueba):
    entrar("docente").put(_url(laboratorio), json=rubrica_de_prueba(pesos=(10, 10, 10)))
    r = entrar("estudiante").get(_url(laboratorio))
    assert r.status_code == 404
    assert r.json()["detail"] == "Este laboratorio todavía no tiene una rúbrica lista."


def test_laboratorio_sin_rubrica_da_404(entrar, laboratorio):
    r = entrar("docente").get(_url(laboratorio))
    assert r.status_code == 404


def test_rubrica_de_un_laboratorio_que_no_existe_da_404(entrar, rubrica_de_prueba):
    r = entrar("docente").put(f"/api/laboratorios/{uuid4()}/rubrica", json=rubrica_de_prueba())
    assert r.status_code == 404
    assert r.json()["detail"] == "Ese laboratorio no existe."


def test_la_estructura_no_acepta_campos_de_sobra(entrar, laboratorio, rubrica_de_prueba):
    datos = rubrica_de_prueba()
    datos["criterios"][0]["nota"] = 5
    r = entrar("docente").put(_url(laboratorio), json=datos)
    assert r.status_code == 422


def test_una_version_guardada_no_se_puede_cambiar_ni_borrar(entrar, laboratorio, db, rubrica_de_prueba):
    v1 = entrar("docente").put(_url(laboratorio), json=rubrica_de_prueba()).json()
    version = db.get(RubricaVersion, UUID(v1["id"]))
    version.valida = False
    with pytest.raises(ValueError, match="no se editan"):
        db.commit()
    db.rollback()
    db.delete(db.get(RubricaVersion, UUID(v1["id"])))
    with pytest.raises(ValueError, match="no se editan"):
        db.commit()


def test_la_version_vigente_es_la_ultima(db, laboratorio, crear_usuario, rubrica_de_prueba):
    from app.esquemas import RubricaEstructura

    docente = crear_usuario("docente")
    for pesos in [(40, 30, 30), (50, 25, 25)]:
        versiones.guardar_version(
            db,
            laboratorio.id,
            RubricaEstructura.model_validate(rubrica_de_prueba(pesos)),
            origen="editor",
            creada_por=docente.id,
        )
    db.commit()
    assert versiones.vigente(db, laboratorio.id).numero == 2
