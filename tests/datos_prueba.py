"""Datos que comparten varias pruebas."""


def rubrica_de_prueba(pesos=(40, 30, 30)) -> dict:
    """Rúbrica en el formato de RubricaEstructura, con los pesos pedidos."""
    return {
        "laboratorio": "Laboratorio 1: agentes",
        "criterios": [
            {
                "id": f"c{i}",
                "nombre": f"Criterio {i}",
                "competencia": "Diseño de agentes",
                "peso": peso,
                "niveles": [
                    {"id": "bajo", "nombre": "Bajo", "descriptor": "No cumple", "valor": 1},
                    {"id": "medio", "nombre": "Medio", "descriptor": "Cumple en parte", "valor": 2},
                    {"id": "alto", "nombre": "Alto", "descriptor": "Cumple todo", "valor": 3},
                ],
            }
            for i, peso in enumerate(pesos, start=1)
        ],
    }
