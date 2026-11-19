"""Tablero del estudiante (D-25): solo lo publicado cuenta (RNF-09)."""

from test_revision import _url, ajustar


def test_sin_entregas_muestra_los_laboratorios_pendientes(entrar, laboratorio):
    estudiante = entrar("estudiante")
    r = estudiante.get("/api/mi-tablero")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["laboratorios"] == 1
    assert [p["laboratorio_id"] for p in datos["pendientes"]] == [str(laboratorio.id)]
    assert (datos["entregados"], datos["esperando"], datos["publicados"]) == (0, 0, 0)
    assert datos["promedio"] is None and datos["ultima"] is None


def test_solo_el_estudiante_tiene_mi_tablero(entrar):
    assert entrar("docente").get("/api/mi-tablero").status_code == 403
    assert entrar("administrador").get("/api/mi-tablero").status_code == 403


def test_antes_de_publicar_no_se_ve_ninguna_nota(evaluada, dueno):
    datos = dueno.get("/api/mi-tablero").json()  # la evaluación está en revisión, con nota 5,0
    assert (datos["entregados"], datos["esperando"], datos["publicados"]) == (1, 1, 0)
    assert datos["pendientes"] == []
    assert datos["promedio"] is None and datos["ultima"] is None
    assert datos["fortalezas"] == [] and datos["por_mejorar"] == []


def test_despues_de_publicar(evaluada, dueno):
    docente, evaluacion = evaluada
    assert ajustar(docente, evaluacion, "c1", "bajo").status_code == 200
    assert docente.post(_url(evaluacion, "aprobar")).status_code == 200
    assert docente.post(_url(evaluacion, "publicar")).status_code == 200

    datos = dueno.get("/api/mi-tablero").json()
    assert (datos["esperando"], datos["publicados"], datos["promedio"], datos["nivel"]) == (
        0,
        1,
        3.7,
        "Medio",
    )
    ultima = datos["ultima"]
    assert (ultima["evaluacion_id"], ultima["nota"], ultima["cambio"]) == (evaluacion["id"], 3.7, None)
    assert datos["por_mejorar"][0]["promedio"] == 1.7  # c1 en 'bajo'
    assert datos["fortalezas"][0]["promedio"] == 5.0


def test_cada_estudiante_ve_solo_lo_suyo(evaluada, entrar):
    docente, evaluacion = evaluada
    docente.post(_url(evaluacion, "aprobar"))
    docente.post(_url(evaluacion, "publicar"))
    otro = entrar("estudiante", correo="otro.estudiante@umanizales.edu.co")
    datos = otro.get("/api/mi-tablero").json()
    assert (datos["publicados"], datos["promedio"], datos["ultima"]) == (0, None, None)
