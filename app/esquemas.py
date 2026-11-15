"""Contrato de datos del proyecto.

Aquí viven los modelos que comparten los módulos y los que validan la salida
de la IA. Todos los modelos de salida de la IA tienen extra="forbid": si el
modelo agrega un campo que no está aquí (por ejemplo una "nota"), se rechaza.
"""

from pydantic import BaseModel, ConfigDict, Field

TOLERANCIA_PESOS = 0.01


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- Rúbricas ----------


class Nivel(Estricto):
    id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    descriptor: str
    valor: float = Field(ge=0)


class Criterio(Estricto):
    id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    competencia: str
    peso: float = Field(gt=0, le=100, description="Porcentaje; todos suman 100")
    niveles: list[Nivel] = Field(min_length=2)

    @property
    def valor_maximo(self) -> float:
        return max(n.valor for n in self.niveles)


class RubricaEstructura(Estricto):
    laboratorio: str
    criterios: list[Criterio] = Field(min_length=1)


def validar_rubrica(rubrica: RubricaEstructura) -> list[str]:
    """Devuelve la lista de errores de la rúbrica. Lista vacía = válida (RF-05)."""
    errores: list[str] = []

    suma = sum(c.peso for c in rubrica.criterios)
    if abs(suma - 100) > TOLERANCIA_PESOS:
        errores.append(f"Los pesos suman {suma:g} %, deben sumar 100 %.")

    ids = [c.id for c in rubrica.criterios]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        errores.append(f"Criterios con id repetido: {', '.join(repetidos)}.")

    for c in rubrica.criterios:
        ids_niveles = [n.id for n in c.niveles]
        if len(set(ids_niveles)) != len(ids_niveles):
            errores.append(f"El criterio '{c.nombre}' tiene niveles con id repetido.")
        if c.valor_maximo <= 0:
            errores.append(f"El criterio '{c.nombre}' no tiene ningún nivel con valor mayor a 0.")
        sin_descriptor = [n.nombre for n in c.niveles if not n.descriptor]
        if sin_descriptor:
            errores.append(
                f"El criterio '{c.nombre}' tiene niveles sin descriptor: {', '.join(sin_descriptor)}."
            )
        if not c.competencia:
            errores.append(f"El criterio '{c.nombre}' no tiene competencia asociada.")

    return errores


# ---------- Salida de la IA por criterio (RF-11) ----------


class Evidencia(Estricto):
    archivo: str = Field(min_length=1, description='Ej. "informe.pdf" o "src/agente.py"')
    ubicacion: str = Field(min_length=1, description='Ej. "página 4" o "líneas 20-35"')
    fragmento: str = Field(min_length=1, max_length=300, description="Texto copiado tal cual")


class ResultadoCriterio(Estricto):
    criterio_id: str
    nivel_id: str
    justificacion: str = Field(min_length=1)
    evidencias: list[Evidencia] = Field(min_length=1)
    fortalezas: list[str]
    debilidades: list[str]
    recomendaciones: list[str]
    # A propósito NO hay campo de nota: la IA no la calcula.
