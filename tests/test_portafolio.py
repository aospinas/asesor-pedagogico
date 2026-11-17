"""Portafolio por estudiante, cohorte y laboratorio (RF-08; fila F2 de la matriz)."""

from uuid import uuid4

from test_entregas import REPO, subir

from app.modelos import Cohorte, Laboratorio


def test_la_entrega_guarda_la_version_de_rubrica(
    entrar, laboratorio, rubrica_lista, almacen, rubrica_de_prueba
):
    """La prueba de la matriz: aunque la rúbrica cambie después, la entrega sigue con la suya."""
    estudiante = entrar("estudiante")
    subir(estudiante, laboratorio, enlace=REPO)
    entrar("docente").put(f"/api/laboratorios/{laboratorio.id}/rubrica", json=rubrica_de_prueba((50, 25, 25)))
    subir(estudiante, laboratorio, enlace=REPO)

    portafolio = estudiante.get(f"/api/portafolio/{estudiante.usuario.id}").json()
    entregas = portafolio["cohortes"][0]["laboratorios"][0]["entregas"]
    assert [e["rubrica_version_numero"] for e in entregas] == [2, 1]


def test_se_organiza_por_cohorte_y_laboratorio(
    entrar, laboratorio, rubrica_lista, almacen, db, crear_usuario
):
    from datos_prueba import rubrica_de_prueba

    from app.esquemas import RubricaEstructura
    from app.rubricas import versiones

    otra = Cohorte(nombre="Cohorte 2", periodo="2027-1")
    db.add(otra)
    db.flush()
    lab2 = Laboratorio(cohorte_id=otra.id, titulo="Lab RAG", descripcion="d", objetivos="o", temas_ia=[])
    db.add(lab2)
    db.flush()
    versiones.guardar_version(
        db,
        lab2.id,
        RubricaEstructura.model_validate(rubrica_de_prueba()),
        origen="editor",
        creada_por=crear_usuario("docente", correo="otra@umanizales.edu.co").id,
    )
    db.commit()

    estudiante = entrar("estudiante")
    subir(estudiante, laboratorio, enlace=REPO)
    subir(estudiante, lab2, enlace=REPO)

    portafolio = entrar("docente").get(f"/api/portafolio/{estudiante.usuario.id}").json()
    assert portafolio["nombre"] == "Persona estudiante"
    resumen = [
        (c["nombre"], [(lab["titulo"], len(lab["entregas"])) for lab in c["laboratorios"]])
        for c in portafolio["cohortes"]
    ]
    assert resumen == [("Cohorte 1", [("Laboratorio 1", 1)]), ("Cohorte 2", [("Lab RAG", 1)])]


def test_un_portafolio_sin_entregas_esta_vacio(entrar):
    estudiante = entrar("estudiante")
    r = estudiante.get(f"/api/portafolio/{estudiante.usuario.id}")
    assert r.status_code == 200
    assert r.json()["cohortes"] == []


def test_el_estudiante_solo_ve_su_portafolio(entrar):
    ana = entrar("estudiante", correo="ana@umanizales.edu.co")
    beto = entrar("estudiante", correo="beto@umanizales.edu.co")
    assert beto.get(f"/api/portafolio/{ana.usuario.id}").status_code == 404


def test_portafolio_de_alguien_que_no_es_estudiante_da_404(entrar):
    docente = entrar("docente")
    assert docente.get(f"/api/portafolio/{docente.usuario.id}").status_code == 404
    assert docente.get(f"/api/portafolio/{uuid4()}").status_code == 404


def test_el_docente_ve_la_lista_de_estudiantes(entrar):
    entrar("estudiante", correo="ana@umanizales.edu.co")
    docente = entrar("docente")
    lista = docente.get("/api/estudiantes").json()
    assert [e["correo"] for e in lista] == ["ana@umanizales.edu.co"]
    assert all("hash" not in str(e) for e in lista)
