"""Configuración de IA y panel de costos por la API (RF-19, RF-20, CU-08)."""

from uuid import UUID

import pytest

from app.api import config_ia as rutas
from app.ia.cliente import ErrorIA, Uso
from app.modelos import Auditoria, Evaluacion

OPENROUTER = {"proveedor": "openrouter", "modelo": "algun/modelo", "base_url": "https://openrouter.ai/api/v1"}


def test_sin_configurar_se_dice_y_nunca_se_muestra_la_llave(entrar):
    vista = entrar("administrador").get("/api/config-ia").json()
    assert vista["origen"] == "sin_configurar"
    assert vista["llave_configurada"] is False
    assert "llave" not in {k for k in vista if k != "llave_configurada"}


def test_el_administrador_elige_proveedor_y_modelo(entrar, db):
    admin = entrar("administrador")
    r = admin.put("/api/config-ia", json=OPENROUTER)
    assert r.status_code == 200, r.text
    assert (r.json()["origen"], r.json()["modelo"]) == ("base", "algun/modelo")
    fila = db.query(Auditoria).filter_by(accion="config_ia_cambiada").one()
    # con base_url (a dónde viaja el material) y los precios
    assert fila.detalle["nuevo"] == OPENROUTER | {"precio_entrada_usd": None, "precio_salida_usd": None}


def test_el_costo_usa_los_precios_del_modelo_elegido(
    entrar, laboratorio, rubrica_lista, almacen, ia_evaluador, monkeypatch
):
    """Si el administrador cambia de modelo con sus precios, el panel no queda con los viejos."""
    from test_entregas import REPO, subir

    from app.api import evaluaciones
    from app.config import ajustes
    from app.main import app

    monkeypatch.setattr(ajustes(), "llm_precio_entrada_usd", 0.1)  # los de Render (otro modelo)
    monkeypatch.setattr(ajustes(), "llm_precio_salida_usd", 0.5)
    del app.dependency_overrides[evaluaciones.obtener_config]
    con_precios = OPENROUTER | {"precio_entrada_usd": 1.0, "precio_salida_usd": 5.0}
    vista = entrar("administrador").put("/api/config-ia", json=con_precios).json()
    assert (vista["precio_entrada_usd"], vista["precio_salida_usd"]) == (1.0, 5.0)
    entrega = subir(entrar("estudiante"), laboratorio, enlace=REPO).json()
    docente = entrar("docente")
    lanzada = docente.post(f"/api/entregas/{entrega['id']}/evaluaciones").json()
    resultado = docente.get(f"/api/evaluaciones/{lanzada['id']}").json()
    entrada, salida = resultado["tokens_entrada"], resultado["tokens_salida"]
    assert resultado["costo_usd"] == pytest.approx((entrada * 1.0 + salida * 5.0) / 1_000_000)


def test_sin_precios_del_modelo_se_usan_los_de_las_variables(entrar, monkeypatch):
    from app.config import ajustes

    monkeypatch.setattr(ajustes(), "llm_precio_entrada_usd", 0.1)
    monkeypatch.setattr(ajustes(), "llm_precio_salida_usd", 0.5)
    vista = entrar("administrador").put("/api/config-ia", json=OPENROUTER).json()
    assert (vista["precio_entrada_usd"], vista["precio_salida_usd"]) == (0.1, 0.5)


def test_la_evaluacion_siguiente_usa_lo_que_eligio_el_administrador(
    entrar, laboratorio, rubrica_lista, almacen, ia_evaluador
):
    """CU-08 completo: sin reemplazar obtener_config, la evaluación guarda el modelo elegido."""
    from test_entregas import REPO, subir

    from app.api import evaluaciones
    from app.main import app

    del app.dependency_overrides[evaluaciones.obtener_config]  # la de verdad, que lee la base
    assert entrar("administrador").put("/api/config-ia", json=OPENROUTER).status_code == 200
    entrega = subir(entrar("estudiante"), laboratorio, enlace=REPO).json()
    lanzada = entrar("docente").post(f"/api/entregas/{entrega['id']}/evaluaciones").json()
    assert (lanzada["proveedor"], lanzada["modelo"]) == ("openrouter", "algun/modelo")
    assert ia_evaluador.pedidos[-1]["config"].modelo == "algun/modelo"


@pytest.mark.parametrize(
    "datos",
    [
        {"proveedor": "openai", "modelo": "x", "base_url": "https://evil.co/v1"},
        {"proveedor": "openrouter", "modelo": "x", "base_url": "https://openrouter.ai.evil.co/api/v1"},
        {"proveedor": "ollama", "modelo": "x", "base_url": "http://169.254.169.254/v1"},
        {"proveedor": "ollama", "modelo": "x", "base_url": "http://127.0.0.1:5432/v1"},  # otro servicio
        {"proveedor": "ollama", "modelo": "x", "base_url": "http://localhost:11434/admin"},
        {"proveedor": "openai", "modelo": "x", "base_url": "https://api.openai.com/v1", "llave": "sk-x"},
    ],
)
def test_no_se_acepta_una_direccion_que_podria_llevarse_la_llave(entrar, datos):
    assert entrar("administrador").put("/api/config-ia", json=datos).status_code == 422


def test_el_docente_no_configura_la_ia(entrar):
    assert entrar("docente").put("/api/config-ia", json=OPENROUTER).status_code == 403


@pytest.mark.parametrize("precios", [{"precio_entrada_usd": 1.0}, {"precio_salida_usd": 5.0}])
def test_los_precios_van_los_dos_o_ninguno(entrar, precios):
    """Con uno solo, el costo mezclaría este modelo con los precios de LLM_PRECIO_*."""
    assert entrar("administrador").put("/api/config-ia", json=OPENROUTER | precios).status_code == 422


def test_probar_la_conexion_bien_y_mal(entrar, db):
    from app.main import app

    admin = entrar("administrador")
    admin.put("/api/config-ia", json=OPENROUTER)
    app.dependency_overrides[rutas.obtener_probar] = lambda: lambda config: Uso(config.modelo, 1, 1)
    r = admin.post("/api/config-ia/probar")
    assert r.json() == {
        "ok": True,
        "proveedor": "openrouter",
        "modelo": "algun/modelo",
        "mensaje": "La IA respondió bien.",
    }

    def falla(config):
        raise ErrorIA("No se pudo hablar con la IA. Intenta de nuevo en un momento.")

    app.dependency_overrides[rutas.obtener_probar] = lambda: falla
    r = admin.post("/api/config-ia/probar")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    # los tokens de cada prueba quedan en la auditoría (no son de ninguna evaluación)
    from app.modelos import Auditoria

    pruebas = db.query(Auditoria).filter_by(accion="config_ia_probada").all()
    assert sorted(p.detalle["ok"] for p in pruebas) == [False, True]
    assert next(p for p in pruebas if p.detalle["ok"]).detalle["tokens_entrada"] == 1
    assert r.json()["mensaje"] == "No se pudo hablar con la IA. Intenta de nuevo en un momento."


def test_probar_sin_configurar_avisa(entrar):
    r = entrar("administrador").post("/api/config-ia/probar")
    assert r.status_code == 503
    assert r.json()["detail"] == rutas.SIN_CONFIGURAR


def test_el_panel_de_costos_suma_todo_y_pagina(entrar, laboratorio, rubrica_lista, almacen, db):
    from test_entregas import REPO, subir

    entrega = subir(entrar("estudiante"), laboratorio, enlace=REPO).json()
    admin = entrar("administrador")
    for i in range(3):
        db.add(
            Evaluacion(
                entrega_id=UUID(entrega["id"]),
                rubrica_version_id=UUID(entrega["rubrica_version_id"]),
                lanzada_por=admin.usuario.id,
                estado="en_revision",
                proveedor="openai",
                modelo="gpt-6-luna",
                version_prompt="evaluar_criterio_v1",
                tokens_entrada=1000 * (i + 1),
                tokens_salida=100,
                costo_usd=0.01,
            )
        )
    db.commit()
    costos = admin.get("/api/costos", params={"limite": 2}).json()
    assert (costos["tokens_entrada"], costos["tokens_salida"]) == (6000, 300)
    assert costos["costo_usd"] == pytest.approx(0.03)
    assert len(costos["evaluaciones"]) == 2
