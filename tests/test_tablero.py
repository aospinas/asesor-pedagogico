"""Tablero del docente (D-24): métricas reales calculadas por el backend."""

from test_revision import _url, ajustar


def test_tablero_vacio(entrar):
    docente = entrar("docente")
    r = docente.get("/api/tablero")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["resumen"]["entregas"] == 0
    assert datos["resumen"]["promedio"] is None
    assert [n["cantidad"] for n in datos["niveles"]] == [0, 0, 0, 0]
    assert datos["acuerdo"]["porcentaje"] is None


def test_solo_el_docente_ve_el_tablero(entrar):
    assert entrar("estudiante").get("/api/tablero").status_code == 403
    assert entrar("administrador").get("/api/tablero").status_code == 403


def test_una_entrega_sin_evaluar(caso):
    docente, _, _ = caso
    resumen = docente.get("/api/tablero").json()["resumen"]
    assert (resumen["entregas"], resumen["sin_evaluar"], resumen["estudiantes"]) == (1, 1, 1)


def test_por_revisar_y_luego_publicada(evaluada):
    docente, evaluacion = evaluada
    datos = docente.get("/api/tablero").json()
    assert datos["resumen"]["por_revisar"] == 1
    assert datos["resumen"]["publicadas"] == 0

    # El docente baja c1 (la IA propuso 'alto'), aprueba y publica.
    assert ajustar(docente, evaluacion, "c1", "bajo").status_code == 200
    assert docente.post(_url(evaluacion, "aprobar")).status_code == 200
    assert docente.post(_url(evaluacion, "publicar")).status_code == 200

    datos = docente.get("/api/tablero").json()
    resumen = datos["resumen"]
    assert (resumen["por_revisar"], resumen["publicadas"], resumen["promedio"]) == (0, 1, 3.7)
    assert {n["nivel"]: n["cantidad"] for n in datos["niveles"]}["Medio"] == 1
    lab = datos["laboratorios"][0]
    assert (lab["entregas"], lab["evaluadas"], lab["publicadas"], lab["promedio"]) == (1, 1, 1, 3.7)
    # 3 criterios revisados: el docente cambió 1
    assert datos["acuerdo"] == {"criterios": 3, "iguales": 2, "cambiados": 1, "porcentaje": 66.7}
    # El más débil es c1: 'bajo' vale 1/3 del máximo → 5 × 1/3 = 1,7
    debil = datos["criterios_debiles"][0]
    assert (debil["promedio"], debil["nivel"], debil["evaluaciones"]) == (1.7, "Por fortalecer", 1)
