"""Página del proyecto y bitácora pública (RF-18, RF-22; D-26). Se ven sin sesión."""

from app.api import proyecto


def test_el_proyecto_se_ve_sin_sesion(cliente):
    r = cliente.get("/api/proyecto")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["regla"] == "La IA propone, el backend calcula, el docente aprueba."
    assert len(datos["equipo"]) == 3
    assert all(m["nombre"] and m["rol"] for m in datos["equipo"])
    assert datos["tecnologias"] and datos["aportes"]


def test_la_bitacora_se_ve_sin_sesion_y_trae_cada_modulo(cliente):
    r = cliente.get("/api/bitacora")
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert len(filas) >= 10
    assert filas[0]["fecha"].startswith("2026-")
    assert {"Contrato", "Requisitos"} <= {f["fase"] for f in filas}


def test_leer_bitacora_solo_toma_el_registro():
    texto = "\n".join(
        [
            "## Herramientas",
            "| Herramienta | Fase | Para qué | Limitación |",
            "| a | b | c | d |",
            "## Registro por módulo",
            "| Fecha | Fase | Herramienta | Pidió | Aportó | Problema | Decisión humana |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            "| 2026-11-19 | Tablero | Claude | Pedido | Aporte | Problema | Decisión |",
            "## Reflexión final",
            "| 2026-01-01 | x | x | x | x | x | x |",
        ]
    )
    filas = proyecto.leer_bitacora(texto)
    assert [f.fase for f in filas] == ["Tablero"]
    assert filas[0].decision == "Decisión"


def test_sin_archivo_responde_503(cliente, monkeypatch, tmp_path):
    monkeypatch.setattr(proyecto, "ARCHIVO_BITACORA", tmp_path / "no-existe.md")
    r = cliente.get("/api/bitacora")
    assert r.status_code == 503
    assert r.json()["detail"] == proyecto.SIN_BITACORA
