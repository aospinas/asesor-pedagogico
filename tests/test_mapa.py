"""Mapa mental con temas, laboratorios y nivel (RF-17)."""

from test_informe import _publicar


def test_el_mapa_une_tema_y_laboratorio(db, laboratorio, rubrica_lista, crear_usuario, entrar):
    docente = entrar("docente", correo="docente.mapa@umanizales.edu.co")
    estudiante = crear_usuario("estudiante", correo="est.mapa@umanizales.edu.co")
    _publicar(db, docente, laboratorio, rubrica_lista, estudiante)

    r = docente.get(f"/api/mapa/{estudiante.id}")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    etiquetas = {n["etiqueta"] for n in cuerpo["nodos"]}
    assert "agentes" in etiquetas
    assert laboratorio.titulo in etiquetas
    tema = next(n for n in cuerpo["nodos"] if n["etiqueta"] == "agentes")
    assert tema["nivel"] == "Alto"
    assert any(a["destino"].startswith("lab-") for a in cuerpo["aristas"])


def test_el_estudiante_ve_su_mapa(db, laboratorio, rubrica_lista, entrar):
    docente = entrar("docente", correo="docente.mapa2@umanizales.edu.co")
    sesion = entrar("estudiante", correo="est.mapa2@umanizales.edu.co")
    _publicar(db, docente, laboratorio, rubrica_lista, sesion.usuario)
    propio = sesion.get(f"/api/mapa/{sesion.usuario.id}")
    assert propio.status_code == 200
    assert propio.json()["estudiante_id"] == str(sesion.usuario.id)
