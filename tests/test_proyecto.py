"""Página pública del proyecto y de la bitácora (RF-18, RF-22)."""


def test_el_proyecto_nombra_a_los_tres_integrantes(cliente):
    r = cliente.get("/api/proyecto")
    assert r.status_code == 200, r.text
    nombres = [p["nombre"] for p in r.json()["equipo"]]
    assert nombres == ["Andrés Ospina Silva", "Santiago Arias Aguirre", "Jerónimo Aristizabal"]
    assert "nota" in r.json()["abstract"].lower() or "backend" in r.json()["aportes"][0].lower()


def test_la_bitacora_publica_trae_el_registro(cliente):
    r = cliente.get("/api/bitacora")
    assert r.status_code == 200, r.text
    assert "Bitácora" in r.json()["contenido"]
    assert "Claude" in r.json()["contenido"]
