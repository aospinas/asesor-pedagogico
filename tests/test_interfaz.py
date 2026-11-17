"""El build de React se sirve desde la misma app (D-23).

Se prueba la clase `Interfaz` con una carpeta temporal: así no depende de que exista
frontend/dist (en el CI no existe; en la imagen Docker sí).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import Interfaz


def _cliente(tmp_path) -> TestClient:
    (tmp_path / "index.html").write_text("<div id=raiz></div>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    sitio = FastAPI()

    @sitio.get("/api/prueba")
    def prueba() -> dict:
        return {"ok": True}

    sitio.mount("/", Interfaz(directory=tmp_path), name="interfaz")
    return TestClient(sitio)


def test_pantallas_conocidas_caen_en_index(tmp_path):
    cliente = _cliente(tmp_path)
    for camino in ["/", "/entregas", "/informe", "/publicada/1234", "/revision/abc", "/clave"]:
        respuesta = cliente.get(camino)
        assert respuesta.status_code == 200, camino
        assert "raiz" in respuesta.text


def test_archivos_y_api_se_sirven_normal(tmp_path):
    cliente = _cliente(tmp_path)
    assert cliente.get("/assets/app.js").text == "console.log(1)"
    assert cliente.get("/api/prueba").json() == {"ok": True}


def test_lo_desconocido_da_404(tmp_path):
    cliente = _cliente(tmp_path)
    for camino in ["/no-existe", "/assets/falta.js", "/entregas/x.js", "/api-falsa", "/../main.py"]:
        assert cliente.get(camino).status_code == 404, camino
