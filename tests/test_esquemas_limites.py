"""Pruebas de los límites de seguridad del contrato (hallazgos de la revisión del módulo)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import esquemas as e
from app.evaluador.nota import ErrorDeNota, calcular_nota, nivel_de_dominio

AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC).isoformat()


def usuario(**cambios):
    base = {
        "nombre": "Ana",
        "correo": "ana@umanizales.edu.co",
        "contrasena": "clave-segura-1",
        "rol": "docente",
    }
    return base | cambios


# ---------- Contraseñas y correo (OWASP A07) ----------


def test_contrasena_de_mas_de_72_bytes_se_rechaza():
    # 37 letras "ñ" son 37 caracteres pero 74 bytes: bcrypt no las acepta.
    with pytest.raises(ValidationError):
        e.UsuarioCrear.model_validate(usuario(contrasena="ñ" * 37))
    with pytest.raises(ValidationError):
        e.Credenciales.model_validate({"correo": "ana@umanizales.edu.co", "contrasena": "a" * 73})
    assert e.UsuarioCrear.model_validate(usuario(contrasena="ñ" * 36))


def test_la_contrasena_no_se_recorta():
    u = e.UsuarioCrear.model_validate(usuario(contrasena="  clave con espacios  "))
    assert u.contrasena == "  clave con espacios  "
    with pytest.raises(ValidationError):
        e.UsuarioCrear.model_validate(usuario(contrasena="  abc     "[:9]))


def test_el_correo_queda_en_minusculas():
    assert e.UsuarioCrear.model_validate(usuario(correo="  Ana@UManizales.EDU.co ")).correo == (
        "ana@umanizales.edu.co"
    )
    assert e.Credenciales.model_validate({"correo": "ANA@X.CO", "contrasena": "x"}).correo == "ana@x.co"


@pytest.mark.parametrize(
    "correo", ["a\x00@b.co", "a@b.co\u200b", "<script>alert(1)</script>@x.co", "a@b..co", "a@b"]
)
def test_correo_con_caracteres_raros_se_rechaza(correo):
    with pytest.raises(ValidationError):
        e.UsuarioCrear.model_validate(usuario(correo=correo))


def test_cambio_de_contrasena_pide_la_actual_y_una_nueva_larga():
    assert e.CambioContrasena.model_validate({"actual": "x", "nueva": "nueva-clave-1"})
    with pytest.raises(ValidationError):
        e.CambioContrasena.model_validate({"actual": "x", "nueva": "corta"})
    with pytest.raises(ValidationError):
        e.CambioContrasena.model_validate({"nueva": "nueva-clave-1"})


# ---------- Números raros en la rúbrica (regla 1: la nota) ----------


def nivel(i, valor):
    return {"id": f"n{i}", "nombre": f"Nivel {i}", "descriptor": "Descripción", "valor": valor}


@pytest.mark.parametrize("valor", [float("inf"), float("nan"), 1e308, 101, -1])
def test_valor_de_nivel_fuera_de_rango_se_rechaza(valor):
    with pytest.raises(ValidationError):
        e.Nivel.model_validate(nivel(1, valor))


def test_valor_infinito_en_json_se_rechaza():
    with pytest.raises(ValidationError):
        e.Nivel.model_validate_json('{"id":"n1","nombre":"N","descriptor":"D","valor":Infinity}')


def test_la_nota_nunca_revienta_con_un_error_que_no_sea_el_suyo():
    rubrica = e.RubricaEstructura.model_validate(
        {
            "laboratorio": "Lab",
            "criterios": [
                {
                    "id": "c1",
                    "nombre": "C1",
                    "competencia": "IA",
                    "peso": 100,
                    "niveles": [nivel(0, 0), nivel(1, 100)],
                }
            ],
        }
    )
    assert calcular_nota(rubrica, {"c1": "n1"}) == 5.0
    with pytest.raises(ErrorDeNota):
        calcular_nota(rubrica, {"c1": "no-existe"})


def test_nivel_de_dominio_es_una_lista_cerrada():
    assert nivel_de_dominio(4.6) is e.NivelDominio.ALTO
    assert {n.value for n in e.NivelDominio} == {"Alto", "Medio", "Básico", "Por fortalecer"}


# ---------- Topes de tamaño (OWASP LLM10) ----------


def respuesta_ia(**cambios):
    base = {
        "criterio_id": "c1",
        "nivel_id": "n3",
        "justificacion": "Usa tool calling.",
        "evidencias": [{"archivo": "src/agente.py", "ubicacion": "líneas 1-5", "fragmento": "tools=[]"}],
        "fortalezas": [],
        "debilidades": [],
        "recomendaciones": [],
    }
    return base | cambios


@pytest.mark.parametrize(
    "cambios",
    [
        {"justificacion": "a" * 2001},
        {"fortalezas": ["ok"] * 11},
        {"debilidades": ["a" * 501]},
        {"recomendaciones": [""]},
        {"evidencias": [{"archivo": "a.py", "ubicacion": "línea 1", "fragmento": "x"}] * 11},
    ],
)
def test_respuesta_de_la_ia_demasiado_grande_se_rechaza(cambios):
    with pytest.raises(ValidationError):
        e.ResultadoCriterio.model_validate(respuesta_ia(**cambios))


def test_respuesta_normal_de_la_ia_pasa():
    assert e.ResultadoCriterio.model_validate(respuesta_ia(fortalezas=["Código claro"] * 10))


def test_rubrica_con_demasiados_criterios_o_niveles_se_rechaza():
    criterio = {
        "id": "c1",
        "nombre": "C",
        "competencia": "IA",
        "peso": 1,
        "niveles": [nivel(0, 0), nivel(1, 1)],
    }
    with pytest.raises(ValidationError):
        e.RubricaEstructura.model_validate({"laboratorio": "Lab", "criterios": [criterio] * 31})
    with pytest.raises(ValidationError):
        e.Criterio.model_validate(criterio | {"niveles": [nivel(i, i) for i in range(11)]})


def test_salida_del_sandbox_tiene_tope():
    base = {
        "tipo": "pruebas",
        "comando": "pytest",
        "codigo_salida": 0,
        "duracion_ms": 5,
        "tiempo_agotado": False,
    }
    assert e.VerificacionCodigo.model_validate(base | {"salida": "a" * 20000})
    with pytest.raises(ValidationError):
        e.VerificacionCodigo.model_validate(base | {"salida": "a" * 20001})


# ---------- Nombres de archivo (OWASP A05) ----------


@pytest.mark.parametrize(
    "nombre", ["../../etc/passwd", "/etc/passwd", "src/../../x.py", "..", "C:\\x.py", "c:/x.py", "a\\b.py"]
)
def test_nombre_de_archivo_tramposo_se_rechaza(nombre):
    with pytest.raises(ValidationError):
        e.Evidencia.model_validate({"archivo": nombre, "ubicacion": "línea 1", "fragmento": "x"})
    with pytest.raises(ValidationError):
        e.EvidenciaArchivo.model_validate(
            {
                "id": str(uuid4()),
                "entrega_id": str(uuid4()),
                "tipo": "codigo",
                "nombre": nombre,
                "sha256": "a" * 64,
            }
        )


@pytest.mark.parametrize("nombre", ["informe.pdf", "src/agente.py", "notas..finales.txt", "Lab 02/código.py"])
def test_nombre_de_archivo_normal_pasa(nombre):
    assert e.Evidencia.model_validate({"archivo": nombre, "ubicacion": "línea 1", "fragmento": "x"})


def test_la_entrega_guardada_tambien_revisa_el_enlace():
    base = {
        "id": str(uuid4()),
        "estudiante_id": str(uuid4()),
        "laboratorio_id": str(uuid4()),
        "rubrica_version_id": str(uuid4()),
        "evidencias": [],
        "fecha": AHORA,
    }
    assert e.Entrega.model_validate(base | {"enlace_github": "https://github.com/ana/lab"})
    with pytest.raises(ValidationError):
        e.Entrega.model_validate(base | {"enlace_github": "https://malo.co/ana/lab"})


# ---------- Dirección del proveedor de IA (que la llave no salga a otro servidor) ----------


def config(proveedor, base_url):
    return {"proveedor": proveedor, "modelo": "x", "base_url": base_url}


@pytest.mark.parametrize(
    ("proveedor", "url"),
    [
        ("openai", "https://evil.co/v1"),
        ("openai", "http://api.openai.com/v1"),
        ("openai", "https://api.openai.com.evil.co/v1"),
        ("openai", "https://u:p@api.openai.com/v1"),
        ("openai", "https://api.openai.com/v1?k=sk-123"),
        ("openai", "https://api.openai.com#@evil.co/v1"),
        ("openai", "https://api.openai.com/v1/../../otro"),
        ("openrouter", "https://api.openai.com/v1"),
        ("ollama", "http://169.254.169.254/latest"),
        ("ollama", "http://0/"),
        ("ollama", "http://evil.co:11434/v1"),
        ("ollama", "http://localhost@evil.co/v1"),
        ("ollama", "http://u:p@localhost:11434/v1"),
        ("ollama", "http://localhost:11434/v1?x=1"),
        ("ollama", "http://localhost:puerto/v1"),
        ("ollama", "localhost:11434/v1"),
    ],
)
def test_direccion_de_ia_no_permitida_se_rechaza(proveedor, url, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOSTS_PERMITIDOS", raising=False)
    with pytest.raises(ValidationError):
        e.ConfigIA.model_validate(config(proveedor, url))


@pytest.mark.parametrize(
    ("proveedor", "url"),
    [
        ("openai", "https://api.openai.com/v1"),
        ("openai", "https://api.openai.com/v1/"),
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("ollama", "http://localhost:11434/v1"),
        ("ollama", "http://127.0.0.1:11434/v1"),
    ],
)
def test_direccion_de_ia_permitida_pasa(proveedor, url, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOSTS_PERMITIDOS", raising=False)
    assert e.ConfigIA.model_validate(config(proveedor, url))


def test_ollama_en_otro_equipo_solo_si_esta_en_la_lista(monkeypatch):
    url = "http://pc-del-salon:11434/v1"
    monkeypatch.delenv("OLLAMA_HOSTS_PERMITIDOS", raising=False)
    with pytest.raises(ValidationError):
        e.ConfigIA.model_validate(config("ollama", url))
    monkeypatch.setenv("OLLAMA_HOSTS_PERMITIDOS", "localhost, PC-del-Salon")
    assert e.ConfigIA.model_validate(config("ollama", url))


# ---------- Modelos nuevos ----------


def test_salidas_nuevas_de_la_ia_no_aceptan_nota():
    plan = {
        "resumen": "Reforzar agentes.",
        "acciones": [{"tema": "Agentes", "que_hacer": "Repetir el Lab 02", "recursos": []}],
    }
    assert e.PlanFortalecimiento.model_validate(plan)
    with pytest.raises(ValidationError):
        e.PlanFortalecimiento.model_validate(plan | {"nota": 4.0})

    temas = {"temas": [{"categoria": "Agentes", "tema": "Tool calling"}]}
    assert e.TemasSugeridos.model_validate(temas)
    with pytest.raises(ValidationError):
        e.TemasSugeridos.model_validate({"temas": []})


def test_la_traza_no_lleva_nota_ni_texto_de_los_criterios():
    campos = set(e.TrazaEvaluacion.model_fields)
    assert {"evidencias", "aprobada_por", "version_prompt", "modelo", "proveedor", "revisiones"} <= campos
    assert not {c for c in campos if "nota" in c or c == "criterios"}


def test_resumen_de_la_bandeja_lleva_el_motivo():
    r = e.EvaluacionResumen.model_validate(
        {
            "id": str(uuid4()),
            "entrega_id": str(uuid4()),
            "laboratorio_id": str(uuid4()),
            "estudiante_id": str(uuid4()),
            "estado": "en_revision",
            "nota_preliminar": 3.9,
            "motivos": ["cita_no_encontrada", "alerta_inyeccion"],
            "fecha": AHORA,
        }
    )
    assert e.MotivoPrioridad.ALERTA_INYECCION in r.motivos


def test_version_de_rubrica_guarda_numero_y_errores():
    datos = {
        "id": str(uuid4()),
        "rubrica_id": str(uuid4()),
        "numero": 1,
        "estructura": {
            "laboratorio": "Lab",
            "criterios": [
                {
                    "id": "c1",
                    "nombre": "C",
                    "competencia": "IA",
                    "peso": 90,
                    "niveles": [nivel(0, 0), nivel(1, 1)],
                }
            ],
        },
        "valida": False,
        "errores": ["Los pesos suman 90 %, deben sumar 100 %."],
        "creada_por": str(uuid4()),
        "fecha": AHORA,
    }
    assert e.RubricaVersion.model_validate(datos).numero == 1
    with pytest.raises(ValidationError):
        e.RubricaVersion.model_validate(datos | {"numero": 0})


def test_mapa_e_informe_usan_el_nivel_de_dominio_cerrado():
    with pytest.raises(ValidationError):
        e.NodoMapa.model_validate({"id": "t1", "tipo": "tema", "etiqueta": "Agentes", "nivel": "Regular"})
    assert e.NodoMapa.model_validate({"id": "t1", "tipo": "tema", "etiqueta": "Agentes", "nivel": "Alto"})
