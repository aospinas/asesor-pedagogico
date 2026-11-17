"""Cálculo de la nota (RF-13, RNF-02).

Este es el ÚNICO lugar del sistema donde se calcula una nota.

    nota = 5.0 x suma( peso_i / 100 x valor_nivel_i / valor_maximo_i )

Se redondea a un decimal con redondeo comercial (3,85 -> 3,9).
"""

from decimal import ROUND_HALF_UP, Decimal

from app import esquemas
from app.esquemas import NivelDominio, RubricaEstructura, validar_rubrica

NOTA_MAXIMA = Decimal(str(esquemas.NOTA_MAXIMA))


class ErrorDeNota(ValueError):
    """La nota no se puede calcular con los datos recibidos."""


def calcular_nota(rubrica: RubricaEstructura, niveles_elegidos: dict[str, str]) -> float:
    """Calcula la nota de 0,0 a 5,0.

    niveles_elegidos: {criterio_id: nivel_id} para TODOS los criterios.
    """
    errores = validar_rubrica(rubrica)
    if errores:
        raise ErrorDeNota("La rúbrica no es válida: " + " ".join(errores))

    total = Decimal("0")
    for criterio in rubrica.criterios:
        nivel_id = niveles_elegidos.get(criterio.id)
        if nivel_id is None:
            raise ErrorDeNota(f"Falta el nivel del criterio '{criterio.nombre}'.")
        nivel = next((n for n in criterio.niveles if n.id == nivel_id), None)
        if nivel is None:
            raise ErrorDeNota(f"El nivel '{nivel_id}' no existe en el criterio '{criterio.nombre}'.")

        peso = Decimal(str(criterio.peso)) / Decimal("100")
        proporcion = Decimal(str(nivel.valor)) / Decimal(str(criterio.valor_maximo))
        total += peso * proporcion

    sobrantes = set(niveles_elegidos) - {c.id for c in rubrica.criterios}
    if sobrantes:
        raise ErrorDeNota(f"Criterios que no existen en la rúbrica: {', '.join(sorted(sobrantes))}.")

    nota = (NOTA_MAXIMA * total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(nota)


def promedio(notas: list[float]) -> float | None:
    """Promedio de notas ya calculadas, a un decimal. No inventa una nota nueva de un criterio."""
    if not notas:
        return None
    total = sum((Decimal(str(nota)) for nota in notas), Decimal("0")) / Decimal(len(notas))
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def nivel_de_dominio(nota: float) -> NivelDominio:
    """Nivel de dominio usado en el informe y el mapa mental."""
    if nota >= 4.5:
        return NivelDominio.ALTO
    if nota >= 3.5:
        return NivelDominio.MEDIO
    if nota >= 3.0:
        return NivelDominio.BASICO
    return NivelDominio.POR_FORTALECER
