"""Cohortes y laboratorios (RF-03, fila F1 de la matriz del SRS)."""

from uuid import uuid4

from app.modelos import Auditoria

LAB = {
    "titulo": "Laboratorio 2: RAG",
    "descripcion": "Recuperación aumentada",
    "objetivos": "Construir un RAG con citas",
    "temas_ia": ["rag", "embeddings"],
}


def _crear_cohorte(cliente, nombre="Cohorte 1", periodo="2026-2"):
    return cliente.post("/api/cohortes", json={"nombre": nombre, "periodo": periodo})


def test_el_docente_crea_cohorte_y_laboratorio(entrar, db):
    docente = entrar("docente")
    r = _crear_cohorte(docente)
    assert r.status_code == 201, r.text
    cohorte = r.json()

    r = docente.post("/api/laboratorios", json=LAB | {"cohorte_id": cohorte["id"]})
    assert r.status_code == 201, r.text
    lab = r.json()
    assert lab["titulo"] == LAB["titulo"]
    assert lab["temas_ia"] == ["rag", "embeddings"]

    acciones = [a.accion for a in db.query(Auditoria).order_by(Auditoria.fecha)]
    assert acciones[-2:] == ["cohorte_creada", "laboratorio_creado"]


def test_todos_ven_las_cohortes_y_los_laboratorios(entrar, laboratorio):
    estudiante = entrar("estudiante")
    assert [c["nombre"] for c in estudiante.get("/api/cohortes").json()] == ["Cohorte 1"]
    labs = estudiante.get("/api/laboratorios").json()
    assert [lab["id"] for lab in labs] == [str(laboratorio.id)]
    assert estudiante.get(f"/api/laboratorios/{laboratorio.id}").json()["titulo"] == "Laboratorio 1"


def test_se_filtran_los_laboratorios_por_cohorte(entrar, laboratorio):
    docente = entrar("docente")
    assert (
        len(docente.get("/api/laboratorios", params={"cohorte_id": str(laboratorio.cohorte_id)}).json()) == 1
    )
    assert docente.get("/api/laboratorios", params={"cohorte_id": str(uuid4())}).json() == []


def test_cohorte_repetida_da_409(entrar):
    docente = entrar("docente")
    assert _crear_cohorte(docente).status_code == 201
    r = _crear_cohorte(docente)
    assert r.status_code == 409
    assert "Ya existe" in r.json()["detail"]


def test_laboratorio_con_cohorte_que_no_existe_da_404(entrar):
    docente = entrar("docente")
    r = docente.post("/api/laboratorios", json=LAB | {"cohorte_id": str(uuid4())})
    assert r.status_code == 404
    assert r.json()["detail"] == "Esa cohorte no existe."


def test_laboratorio_que_no_existe_da_404(entrar):
    r = entrar("docente").get(f"/api/laboratorios/{uuid4()}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Ese laboratorio no existe."


def test_el_docente_edita_un_laboratorio_y_queda_auditado(entrar, laboratorio, db):
    docente = entrar("docente")
    r = docente.patch(f"/api/laboratorios/{laboratorio.id}", json={"titulo": "Lab 1 (nuevo)"})
    assert r.status_code == 200, r.text
    assert r.json()["titulo"] == "Lab 1 (nuevo)"
    assert r.json()["descripcion"] == "Agentes con herramientas"

    fila = db.query(Auditoria).filter_by(accion="laboratorio_editado").one()
    assert fila.detalle == {
        "cambios": [{"campo": "titulo", "anterior": "Laboratorio 1", "nuevo": "Lab 1 (nuevo)"}]
    }
    assert fila.entidad_id == str(laboratorio.id)


def test_un_texto_largo_editado_queda_recortado_y_con_huella(entrar, laboratorio, db):
    nueva = "Objetivo nuevo. " * 50
    entrar("docente").patch(f"/api/laboratorios/{laboratorio.id}", json={"objetivos": nueva})
    cambio = db.query(Auditoria).filter_by(accion="laboratorio_editado").one().detalle["cambios"][0]
    assert cambio["anterior"] == "Construir un agente"
    assert len(cambio["nuevo"]["inicio"]) == 200
    assert len(cambio["nuevo"]["sha256"]) == 64


def test_editar_sin_cambios_no_audita(entrar, laboratorio, db):
    docente = entrar("docente")
    r = docente.patch(f"/api/laboratorios/{laboratorio.id}", json={"titulo": "Laboratorio 1"})
    assert r.status_code == 200
    assert db.query(Auditoria).filter_by(accion="laboratorio_editado").count() == 0


def test_editar_no_acepta_campos_de_sobra(entrar, laboratorio):
    r = entrar("docente").patch(f"/api/laboratorios/{laboratorio.id}", json={"id": str(uuid4())})
    assert r.status_code == 422


def test_el_estudiante_no_crea_ni_edita(entrar, laboratorio):
    estudiante = entrar("estudiante")
    assert _crear_cohorte(estudiante).status_code == 403
    assert estudiante.patch(f"/api/laboratorios/{laboratorio.id}", json={"titulo": "x"}).status_code == 403


def test_titulo_vacio_se_rechaza(entrar, laboratorio):
    docente = entrar("docente")
    r = docente.post(
        "/api/laboratorios", json=LAB | {"cohorte_id": str(laboratorio.cohorte_id), "titulo": " "}
    )
    assert r.status_code == 422
