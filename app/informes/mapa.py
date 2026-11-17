"""Mapa mental de temas de IA (RF-17): categoría → tema → laboratorio, listo para Cytoscape.js.

Se calcula al momento desde las evaluaciones publicadas (SRS sección 8: sin tabla propia).
- Cada tema lleva su nivel de dominio y "qué profundizar" (del plan, si lo hay; si no, las
  recomendaciones que el docente aprobó en esos laboratorios).
- Cada laboratorio lleva su nivel y hasta MAXIMO_EVIDENCIAS citas ENCONTRADAS (LLM09).
- Los ids de los nodos los arma el backend: "cat:N", "tema:N" y "lab:<uuid>" (el texto del
  docente nunca va en un id).
"""

import uuid

from app.esquemas import AristaMapa, Evidencia, MapaMental, NodoMapa, PlanFortalecimiento, TipoNodo
from app.informes.calculo import Datos, nivel_de, partir_tema

MAXIMO_EVIDENCIAS = 5
MAXIMO_PROFUNDIZAR = 5


def _citas(publicada) -> list[Evidencia]:
    citas = []
    for criterio in publicada.criterios:
        for e in criterio.evidencias:
            if e.get("encontrada") is True and all(e.get(k) for k in ("archivo", "ubicacion", "fragmento")):
                citas.append(
                    Evidencia(archivo=e["archivo"], ubicacion=e["ubicacion"], fragmento=e["fragmento"])
                )
            if len(citas) >= MAXIMO_EVIDENCIAS:
                return citas
    return citas


def armar(estudiante_id: uuid.UUID, datos: Datos, plan: PlanFortalecimiento | None) -> MapaMental:
    nodos: list[NodoMapa] = []
    aristas: list[AristaMapa] = []
    del_plan: dict[str, list[str]] = {}
    for accion in plan.acciones if plan else []:
        del_plan.setdefault(accion.tema, []).append(accion.que_hacer)
    publicadas = {p.laboratorio.id: p for p in datos.publicadas}

    # Laboratorios
    for p in datos.publicadas:
        nodos.append(
            NodoMapa(
                id=f"lab:{p.laboratorio.id}",
                tipo=TipoNodo.LABORATORIO,
                etiqueta=p.laboratorio.titulo,
                nivel=nivel_de(p.evaluacion.nota_final),
                evidencias=_citas(p),
            )
        )

    # Categorías y temas
    categorias: dict[str, str] = {}
    for n, tema in enumerate(datos.temas):
        if tema.categoria not in categorias:
            categorias[tema.categoria] = f"cat:{len(categorias)}"
            nodos.append(
                NodoMapa(id=categorias[tema.categoria], tipo=TipoNodo.CATEGORIA, etiqueta=tema.categoria)
            )
        profundizar = list(del_plan.get(tema.tema, []))
        if not profundizar:  # sin plan: lo que el docente recomendó en esos laboratorios
            for lab_id in tema.laboratorios:
                for criterio in publicadas[lab_id].criterios:
                    profundizar.extend(r for r in criterio.recomendaciones if r not in profundizar)
        id_tema = f"tema:{n}"
        nodos.append(
            NodoMapa(
                id=id_tema,
                tipo=TipoNodo.TEMA,
                etiqueta=tema.tema,
                nivel=tema.nivel,
                que_profundizar=profundizar[:MAXIMO_PROFUNDIZAR],
            )
        )
        aristas.append(AristaMapa(origen=categorias[tema.categoria], destino=id_tema))
        for lab_id in tema.laboratorios:
            aristas.append(AristaMapa(origen=id_tema, destino=f"lab:{lab_id}"))
    return MapaMental(estudiante_id=estudiante_id, nodos=nodos, aristas=aristas)


__all__ = ["armar", "partir_tema"]
