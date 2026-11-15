import pytest
from pydantic import ValidationError

from app.esquemas import Criterio, Nivel, ResultadoCriterio, RubricaEstructura, validar_rubrica
from app.evaluador.nota import ErrorDeNota, calcular_nota, nivel_de_dominio


def niveles():
    return [
        Nivel(id="n0", nombre="No cumple", descriptor="No hay evidencia", valor=0),
        Nivel(id="n1", nombre="Inicial", descriptor="Evidencia mínima", valor=1),
        Nivel(id="n2", nombre="Básico", descriptor="Cumple a medias", valor=2),
        Nivel(id="n3", nombre="Bueno", descriptor="Cumple", valor=3),
        Nivel(id="n4", nombre="Excelente", descriptor="Cumple y va más allá", valor=4),
    ]


def rubrica(pesos=(40, 30, 30)):
    return RubricaEstructura(
        laboratorio="Lab 02",
        criterios=[
            Criterio(id=f"c{i}", nombre=f"Criterio {i}", competencia="IA", peso=p, niveles=niveles())
            for i, p in enumerate(pesos, start=1)
        ],
    )


def test_ejemplo_del_srs_da_3_9():
    # 5,0 x (0,40 x 4/4 + 0,30 x 3/4 + 0,30 x 2/4) = 3,875 -> 3,9
    assert calcular_nota(rubrica(), {"c1": "n4", "c2": "n3", "c3": "n2"}) == 3.9


def test_todo_excelente_da_5():
    assert calcular_nota(rubrica(), {"c1": "n4", "c2": "n4", "c3": "n4"}) == 5.0


def test_todo_en_cero_da_0():
    assert calcular_nota(rubrica(), {"c1": "n0", "c2": "n0", "c3": "n0"}) == 0.0


def test_redondeo_comercial():
    # 5,0 x (0,64 x 4/4 + 0,36 x 1/4) = 3,65 -> 3,7 (round() de Python daría 3,6)
    assert calcular_nota(rubrica((64, 36)), {"c1": "n4", "c2": "n1"}) == 3.7
    # 5,0 x (0,5 x 3/4 + 0,5 x 2/4) = 3,125 -> 3,1
    assert calcular_nota(rubrica((50, 50)), {"c1": "n3", "c2": "n2"}) == 3.1


def test_falta_un_criterio():
    with pytest.raises(ErrorDeNota, match="Falta el nivel"):
        calcular_nota(rubrica(), {"c1": "n4", "c2": "n3"})


def test_nivel_que_no_existe():
    with pytest.raises(ErrorDeNota, match="no existe"):
        calcular_nota(rubrica(), {"c1": "n9", "c2": "n3", "c3": "n2"})


def test_criterio_que_no_existe():
    with pytest.raises(ErrorDeNota, match="no existen"):
        calcular_nota(rubrica(), {"c1": "n4", "c2": "n3", "c3": "n2", "c99": "n1"})


def test_pesos_que_no_suman_100_bloquean():
    malo = rubrica((40, 30, 20))
    assert any("suman 90" in e for e in validar_rubrica(malo))
    with pytest.raises(ErrorDeNota, match="no es válida"):
        calcular_nota(malo, {"c1": "n4", "c2": "n3", "c3": "n2"})


def test_niveles_de_dominio():
    assert nivel_de_dominio(5.0) == "Alto"
    assert nivel_de_dominio(4.5) == "Alto"
    assert nivel_de_dominio(4.4) == "Medio"
    assert nivel_de_dominio(3.5) == "Medio"
    assert nivel_de_dominio(3.0) == "Básico"
    assert nivel_de_dominio(2.9) == "Por fortalecer"


def respuesta_ia(**extra):
    base = {
        "criterio_id": "c1",
        "nivel_id": "n3",
        "justificacion": "Usa tool calling correctamente.",
        "evidencias": [{"archivo": "agente.py", "ubicacion": "líneas 10-20", "fragmento": "tools=[...]"}],
        "fortalezas": ["Código claro"],
        "debilidades": [],
        "recomendaciones": ["Agregar pruebas"],
    }
    return base | extra


def test_la_ia_no_puede_colar_una_nota():
    with pytest.raises(ValidationError):
        ResultadoCriterio.model_validate(respuesta_ia(nota=5.0))


def test_la_ia_debe_citar_al_menos_una_evidencia():
    with pytest.raises(ValidationError):
        ResultadoCriterio.model_validate(respuesta_ia(evidencias=[]))


def test_respuesta_valida_de_la_ia():
    r = ResultadoCriterio.model_validate(respuesta_ia())
    assert r.nivel_id == "n3"
