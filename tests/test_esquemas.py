"""Pruebas del contrato de datos (app/esquemas.py)."""

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app import esquemas
from app.esquemas import (
    AjusteNivel,
    ConfigIA,
    Criterio,
    CriterioEvaluado,
    EntregaCrear,
    EstadoEvaluacion,
    Evaluacion,
    EvaluacionPublicada,
    EvidenciaArchivo,
    Nivel,
    ProveedorIA,
    Rol,
    RubricaEstructura,
    TipoEvidencia,
    UsuarioCrear,
    UsuarioPublico,
    validar_rubrica,
)

AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
SHA = "a" * 64

MODELOS = [
    m
    for _, m in inspect.getmembers(esquemas, inspect.isclass)
    if issubclass(m, BaseModel) and m.__module__ == esquemas.__name__
]

# Los únicos modelos que pueden llevar una nota: los arma el backend, nadie los manda.
MODELOS_CON_NOTA = {
    esquemas.Evaluacion,
    esquemas.EvaluacionPublicada,
    esquemas.EvaluacionResumen,
    esquemas.ResultadoLaboratorio,
}
MODELOS_SIN_NOTA = [m for m in MODELOS if m not in MODELOS_CON_NOTA]


def test_hay_modelos_que_revisar():
    assert len(MODELOS) >= 20


@pytest.mark.parametrize("modelo", MODELOS, ids=lambda m: m.__name__)
def test_todos_los_modelos_rechazan_campos_extra(modelo):
    assert modelo.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("modelo", MODELOS_SIN_NOTA, ids=lambda m: m.__name__)
def test_nadie_puede_escribir_una_nota(modelo):
    assert not [campo for campo in modelo.model_fields if "nota" in campo.lower()]


def test_los_modelos_con_nota_no_son_de_entrada():
    # Si un modelo nuevo necesita nota, hay que agregarlo aquí a propósito.
    assert {m.__name__ for m in MODELOS_CON_NOTA} == {
        "Evaluacion",
        "EvaluacionPublicada",
        "EvaluacionResumen",
        "ResultadoLaboratorio",
    }


# ---------- Usuarios ----------


def usuario(**cambios):
    base = {
        "nombre": "Ana Pérez",
        "correo": "ana@umanizales.edu.co",
        "contrasena": "clave-segura-1",
        "rol": "estudiante",
    }
    return base | cambios


def test_usuario_valido():
    u = UsuarioCrear.model_validate(usuario())
    assert u.rol is Rol.ESTUDIANTE


def test_contrasena_de_9_caracteres_se_rechaza():
    with pytest.raises(ValidationError):
        UsuarioCrear.model_validate(usuario(contrasena="123456789"))


def test_contrasena_de_10_caracteres_pasa():
    assert UsuarioCrear.model_validate(usuario(contrasena="1234567890"))


@pytest.mark.parametrize("correo", ["sin-arroba", "a@b", "a b@c.co", "@c.co"])
def test_correo_mal_escrito_se_rechaza(correo):
    with pytest.raises(ValidationError):
        UsuarioCrear.model_validate(usuario(correo=correo))


def test_rol_que_no_existe_se_rechaza():
    with pytest.raises(ValidationError):
        UsuarioCrear.model_validate(usuario(rol="superusuario"))


def test_usuario_publico_no_muestra_la_contrasena():
    campos = set(UsuarioPublico.model_fields)
    assert not {c for c in campos if "contrasena" in c or "hash" in c}
    with pytest.raises(ValidationError):
        UsuarioPublico.model_validate(
            {
                "id": str(uuid4()),
                "nombre": "Ana",
                "correo": "ana@umanizales.edu.co",
                "rol": "estudiante",
                "activo": True,
                "hash_contrasena": "x",
            }
        )


# ---------- Rúbricas ----------


def nivel(i, valor):
    return Nivel(id=f"n{i}", nombre=f"Nivel {i}", descriptor="Descripción", valor=valor)


def rubrica_con(valores):
    return RubricaEstructura(
        laboratorio="Lab 02",
        criterios=[
            Criterio(
                id="c1",
                nombre="Criterio 1",
                competencia="IA",
                peso=100,
                niveles=[nivel(i, v) for i, v in enumerate(valores)],
            )
        ],
    )


@pytest.mark.parametrize("valores", [(0, 1, 2, 3, 4), (4, 3, 2, 1, 0)])
def test_niveles_ordenados_pasan(valores):
    assert validar_rubrica(rubrica_con(valores)) == []


@pytest.mark.parametrize("valores", [(0, 2, 1, 3), (0, 1, 1, 2)])
def test_niveles_desordenados_o_repetidos_bloquean(valores):
    assert any("orden" in e for e in validar_rubrica(rubrica_con(valores)))


# ---------- Entregas y evidencias ----------


def test_sha256_mal_formado_se_rechaza():
    datos = {
        "id": str(uuid4()),
        "entrega_id": str(uuid4()),
        "tipo": "pdf",
        "nombre": "informe.pdf",
        "sha256": "abc123",
    }
    with pytest.raises(ValidationError):
        EvidenciaArchivo.model_validate(datos)
    ok = EvidenciaArchivo.model_validate(datos | {"sha256": SHA})
    assert ok.tipo is TipoEvidencia.PDF


@pytest.mark.parametrize(
    "enlace",
    [
        "http://github.com/ana/lab",
        "https://github.com.malo.co/ana/lab",
        "https://github.com/ana",
        "https://gitlab.com/ana/lab",
        "https://github.com/ana/lab/../../otro",
    ],
)
def test_enlace_que_no_es_un_repo_de_github_se_rechaza(enlace):
    with pytest.raises(ValidationError):
        EntregaCrear.model_validate({"laboratorio_id": str(uuid4()), "enlace_github": enlace})


def test_enlace_de_github_valido():
    e = EntregaCrear.model_validate(
        {"laboratorio_id": str(uuid4()), "enlace_github": "https://github.com/ana-p/lab_02.agente"}
    )
    assert e.enlace_github


# ---------- Evaluaciones ----------


def criterio_evaluado(**cambios):
    base = {
        "criterio_id": "c1",
        "nivel_ia": "n3",
        "nivel_final": "n3",
        "justificacion": "Usa tool calling.",
        "evidencias": [
            {"archivo": "agente.py", "ubicacion": "líneas 1-5", "fragmento": "tools=[]", "encontrada": True}
        ],
        "fortalezas": [],
        "debilidades": [],
        "recomendaciones": [],
    }
    return base | cambios


def evaluacion(**cambios):
    base = {
        "id": str(uuid4()),
        "entrega_id": str(uuid4()),
        "rubrica_version_id": str(uuid4()),
        "estado": "en_revision",
        "proveedor": "openai",
        "modelo": "modelo-x",
        "version_prompt": "evaluar_criterio_v1",
        "criterios": [criterio_evaluado()],
        "verificaciones": [],
        "nota_preliminar": 3.9,
        "nota_final": None,
        "tokens_entrada": 100,
        "tokens_salida": 50,
        "costo_usd": 0.001,
        "alerta_inyeccion": False,
        "fecha": AHORA.isoformat(),
    }
    return base | cambios


def test_evaluacion_valida():
    e = Evaluacion.model_validate(evaluacion())
    assert e.estado is EstadoEvaluacion.EN_REVISION
    assert e.proveedor is ProveedorIA.OPENAI


def test_los_estados_son_los_cinco_del_srs():
    assert {e.value for e in EstadoEvaluacion} == {
        "en_proceso",
        "en_revision",
        "revision_manual",
        "aprobada",
        "publicada",
    }


@pytest.mark.parametrize("nota", [-0.1, 5.1])
def test_nota_fuera_de_0_a_5_se_rechaza(nota):
    with pytest.raises(ValidationError):
        Evaluacion.model_validate(evaluacion(nota_preliminar=nota))


def test_criterio_sin_propuesta_de_la_ia_es_valido():
    c = CriterioEvaluado.model_validate(criterio_evaluado(nivel_ia=None, nivel_final=None, evidencias=[]))
    assert c.nivel_ia is None


def test_lo_que_ve_el_estudiante_no_trae_datos_internos():
    # Lista exacta de lo permitido: un campo nuevo obliga a pensar si el estudiante lo debe ver.
    assert set(EvaluacionPublicada.model_fields) == {
        "id",
        "entrega_id",
        "laboratorio_id",
        "nota_final",
        "criterios",
        "fecha_publicacion",
    }
    assert set(esquemas.CriterioPublicado.model_fields) == {
        "criterio_id",
        "nivel_id",
        "justificacion",
        "evidencias",
        "fortalezas",
        "debilidades",
        "recomendaciones",
    }


# ---------- Revisión docente ----------


def test_ajuste_sin_justificacion_se_rechaza():
    for justificacion in ("", "    "):
        with pytest.raises(ValidationError):
            AjusteNivel.model_validate(
                {"criterio_id": "c1", "nivel_id": "n4", "justificacion": justificacion}
            )


def test_el_docente_no_puede_mandar_una_nota_en_el_ajuste():
    with pytest.raises(ValidationError):
        AjusteNivel.model_validate(
            {"criterio_id": "c1", "nivel_id": "n4", "justificacion": "Sí cumple", "nota": 5.0}
        )


# ---------- Configuración de IA ----------


def test_config_ia_no_guarda_la_llave():
    assert not [c for c in ConfigIA.model_fields if "key" in c or "llave" in c or "clave" in c]
    with pytest.raises(ValidationError):
        ConfigIA.model_validate(
            {
                "proveedor": "openai",
                "modelo": "x",
                "base_url": "https://api.openai.com/v1",
                "api_key": "secreta",
            }
        )


@pytest.mark.parametrize("url", ["ftp://servidor/v1", "javascript:alert(1)", "api.openai.com/v1"])
def test_config_ia_solo_acepta_http_o_https(url):
    with pytest.raises(ValidationError):
        ConfigIA.model_validate({"proveedor": "ollama", "modelo": "x", "base_url": url})
