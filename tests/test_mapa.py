"""Mapa mental (RF-17, CU-07; fila F6 de la matriz del SRS; D-22).

La prueba de la matriz: el JSON trae temas, laboratorios y nivel.
"""

from test_informe import estudiante, ia_plan, publicar  # noqa: F401  (fixtures compartidas)

from app.api import informe as rutas

ENCONTRADA = {
    "archivo": "informe.pdf",
    "ubicacion": "página 1",
    "fragmento": "El agente usa herramientas",
    "encontrada": True,
}
NO_ENCONTRADA = {
    "archivo": "informe.pdf",
    "ubicacion": "página 2",
    "fragmento": "Algo inventado",
    "encontrada": False,
}


def test_el_mapa_une_categoria_tema_y_laboratorio_con_su_nivel(estudiante, publicar, ia_plan):  # noqa: F811
    yo = estudiante.usuario
    lab1, _ = publicar(
        yo, "Cohorte 1", "Lab 01", ["Agentes: herramientas"], 4.8, evidencias=[ENCONTRADA, NO_ENCONTRADA]
    )
    lab2, _ = publicar(yo, "Cohorte 2", "Lab 02", ["Agentes: herramientas", "ML: regresión"], 3.2)
    estudiante.get(f"/api/informe/{yo.id}")  # el informe redacta y guarda el plan; el mapa lo usa
    r = estudiante.get(f"/api/mapa/{yo.id}")
    assert r.status_code == 200, r.text
    mapa = r.json()
    nodos = {n["id"]: n for n in mapa["nodos"]}
    por_tipo = {
        t: sorted(n["etiqueta"] for n in mapa["nodos"] if n["tipo"] == t)
        for t in ("categoria", "tema", "laboratorio")
    }
    assert por_tipo == {
        "categoria": ["Agentes", "ML"],
        "tema": ["herramientas", "regresión"],
        "laboratorio": ["Lab 01", "Lab 02"],
    }
    tema = next(n for n in mapa["nodos"] if n["etiqueta"] == "herramientas")
    assert tema["nivel"] == "Medio"  # (4,8 + 3,2) / 2 = 4,0
    assert tema["que_profundizar"] == ["Practica herramientas"]  # del plan
    lab = nodos[f"lab:{lab1.id}"]
    assert lab["nivel"] == "Alto"
    assert [e["fragmento"] for e in lab["evidencias"]] == ["El agente usa herramientas"]  # solo encontradas
    aristas = {(a["origen"], a["destino"]) for a in mapa["aristas"]}
    assert (tema["id"], f"lab:{lab1.id}") in aristas and (tema["id"], f"lab:{lab2.id}") in aristas
    categoria = next(n for n in mapa["nodos"] if n["etiqueta"] == "Agentes")
    assert (categoria["id"], tema["id"]) in aristas
    # Ningún id lleva texto del docente
    assert all(i.startswith(("cat:", "tema:", "lab:")) for i in nodos)


def test_sin_plan_que_profundizar_sale_de_las_recomendaciones_aprobadas(estudiante, publicar):  # noqa: F811
    from app.main import app

    app.dependency_overrides[rutas.obtener_plan_ia] = lambda: (None, None)
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 3.0, recomendaciones=["Agrega pruebas"])
    mapa = estudiante.get(f"/api/mapa/{estudiante.usuario.id}").json()
    tema = next(n for n in mapa["nodos"] if n["tipo"] == "tema")
    assert (tema["etiqueta"], tema["nivel"], tema["que_profundizar"]) == (
        "Agentes",
        "Básico",
        ["Agrega pruebas"],
    )
    categoria = next(n for n in mapa["nodos"] if n["tipo"] == "categoria")
    assert categoria["etiqueta"] == "Otros temas"


def test_sin_nada_publicado_el_mapa_sale_vacio(estudiante, ia_plan):  # noqa: F811
    mapa = estudiante.get(f"/api/mapa/{estudiante.usuario.id}").json()
    assert (mapa["nodos"], mapa["aristas"]) == ([], [])
