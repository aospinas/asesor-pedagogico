"""Arma el material de la entrega que ve la IA y el índice para verificar las citas.

- El PDF y las diapositivas van por página; el código, con número de línea.
- Las imágenes van como su descripción (la hace la IA con visión, app/evaluador/imagenes.py).
- Todo va como JSON dentro de <entrega>...</entrega> y con cada "<" escapado (\\u003c): así
  ningún texto, nombre de archivo ni ruta del estudiante puede cerrar la etiqueta ni parecer
  una instrucción (OWASP LLM01; pendiente que dejó D-17).
- Hay tope de caracteres (OWASP LLM10), medido ya escapado (un "<" ocupa 6) y contando la
  estructura del JSON de cada parte: lo que no cabe se corta y se avisa con "recortado".
- Cada archivo tiene un nombre único en el material (sin mirar mayúsculas): si un archivo del
  ZIP se llama igual que el informe, se le agrega el tipo, para que una cita no se cruce.
"""

import json
from dataclasses import dataclass, field

from app.esquemas import TipoEvidencia
from app.evaluador.citas import Documento
from app.modelos import Evidencia

MAXIMO_MATERIAL = 60_000  # caracteres (ya escapados) de material que van a la IA en cada criterio
MAXIMO_POR_ARCHIVO_CODIGO = 12_000
# Lo que ocupa la estructura del JSON de cada parte (claves, sangría, número de página...).
# Sin contarlo, cientos de archivos pequeños pasaban el tope (D-19).
COSTO_POR_PARTE = 60


@dataclass
class Material:
    texto: str  # el bloque <entrega>...</entrega>
    documentos: dict[str, Documento] = field(default_factory=dict)
    recortado: bool = False
    texto_plano: str = ""  # el texto del estudiante que ve la IA, para el filtro de inyección


def _escapar(valor) -> str:
    return json.dumps(valor, ensure_ascii=False).replace("<", "\\u003c")


def _con_lineas(texto: str) -> tuple[str, list[str]]:
    lineas = texto.splitlines()
    ancho = len(str(len(lineas)))
    return "\n".join(f"{i:>{ancho}}| {linea}" for i, linea in enumerate(lineas, start=1)), lineas


def _nombre_unico(nombre: str, tipo: str, documentos: dict[str, Documento]) -> str:
    usados = {n.casefold() for n in documentos}
    if nombre.casefold() not in usados:
        return nombre
    candidato, numero = f"{nombre} [{tipo}]", 2
    while candidato.casefold() in usados:
        candidato, numero = f"{nombre} [{tipo} {numero}]", numero + 1
    return candidato


def armar(evidencias: list[Evidencia], verificaciones: list[dict] | None = None) -> Material:
    partes: list[dict] = []
    documentos: dict[str, Documento] = {}
    plano: list[str] = []
    usado = 0
    recortado = False

    def cabe(*valores: str) -> bool:
        """Si caben (medidos ya escapados) los suma a lo usado."""
        nonlocal usado
        largo = sum(len(_escapar(v)) for v in valores) + COSTO_POR_PARTE * len(valores)
        if usado + largo > MAXIMO_MATERIAL:
            return False
        usado += largo
        return True

    # Orden: informe, diapositivas, código, imágenes (lo que más pesa en la rúbrica va primero)
    orden = {"pdf": 0, "diapositivas": 1, "codigo": 2, "imagen": 3}
    for evidencia in sorted(evidencias, key=lambda e: orden.get(e.tipo, 9)):
        extraido = evidencia.texto_extraido or {}
        if evidencia.tipo in (TipoEvidencia.PDF.value, TipoEvidencia.DIAPOSITIVAS.value):
            nombre = _nombre_unico(evidencia.nombre, evidencia.tipo, documentos)
            paginas = list(extraido.get("paginas", []))
            documentos[nombre] = Documento(paginas=paginas)
            recortado = recortado or bool(extraido.get("recortado"))
            if not cabe(nombre):
                recortado = True
                continue
            plano.append(nombre)
            unidad = "pagina" if evidencia.tipo == TipoEvidencia.PDF.value else "diapositiva"
            incluidas = []
            for i, texto in enumerate(paginas, start=1):
                if not texto.strip():
                    continue
                if not cabe(texto):
                    recortado = True
                    break
                incluidas.append({unidad: i, "texto": texto})
                plano.append(texto)
            partes.append({"archivo": nombre, "tipo": evidencia.tipo, "partes": incluidas})
        elif evidencia.tipo == TipoEvidencia.CODIGO.value:
            for archivo in extraido.get("archivos", []):
                ruta = _nombre_unico(archivo["ruta"], "codigo", documentos)
                texto = archivo["texto"]
                numerado, lineas = _con_lineas(texto[:MAXIMO_POR_ARCHIVO_CODIGO])
                documentos[ruta] = Documento(lineas=lineas)
                if not cabe(ruta, numerado):
                    recortado = True
                    continue
                partes.append({"archivo": ruta, "tipo": "codigo", "lineas": numerado})
                # Al filtro va sin números de línea: si no, "ignora las" / "instrucciones" en dos
                # líneas quedaría partido por " 13| ".
                plano.extend([ruta, "\n".join(lineas)])
                recortado = recortado or len(texto) > MAXIMO_POR_ARCHIVO_CODIGO
            omitidos = [o["ruta"] for o in extraido.get("omitidos", [])[:50]]
            if omitidos and cabe(*omitidos):
                partes.append({"tipo": "codigo_omitido", "archivos": omitidos})
                plano.extend(omitidos)
        elif evidencia.tipo == TipoEvidencia.IMAGEN.value:
            descripcion = extraido.get("descripcion")
            if descripcion:
                nombre = _nombre_unico(evidencia.nombre, evidencia.tipo, documentos)
                documentos[nombre] = Documento(texto=descripcion)
                if cabe(nombre, descripcion):
                    partes.append({"archivo": nombre, "tipo": "imagen", "descripcion": descripcion})
                    plano.extend([nombre, descripcion])
                else:
                    recortado = True

    cuerpo = {"archivos": partes, "verificaciones_codigo": verificaciones or [], "recortado": recortado}
    # ensure_ascii=False para que las tildes se lean bien; luego se escapa cada "<".
    datos = json.dumps(cuerpo, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    return Material(
        texto=f"<entrega>\n{datos}\n</entrega>",
        documentos=documentos,
        recortado=recortado,
        texto_plano="\n".join(plano),
    )
