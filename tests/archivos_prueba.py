"""Archivos de prueba armados en memoria: PDF, ZIP, imágenes y diapositivas."""

import io
import zipfile

import pymupdf

TEXTO_INFORME = "Informe del laboratorio 1. El agente usa herramientas para ordenar archivos por tipo."


def pdf(texto: str | None = TEXTO_INFORME, paginas: int = 1, textos: list[str] | None = None) -> bytes:
    """Un PDF de prueba. Con `textos`, una página por texto ("" = página en blanco)."""
    doc = pymupdf.open()
    for i, contenido in enumerate(textos if textos is not None else [texto] * paginas):
        pagina = doc.new_page()
        if contenido:
            pagina.insert_text((72, 72), f"{contenido} Página {i + 1}." if textos is None else contenido)
    contenido = doc.tobytes()
    doc.close()
    return contenido


def zip_codigo(archivos: dict[str, bytes | str] | None = None) -> bytes:
    archivos = archivos or {
        "agente/main.py": "def ordenar(ruta):\n    return sorted(ruta)\n",
        "agente/README.md": "# Agente\n",
        "agente/logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,
    }
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for ruta, datos in archivos.items():
            z.writestr(ruta, datos)
    return memoria.getvalue()


def png() -> bytes:
    doc = pymupdf.open()
    pagina = doc.new_page(width=50, height=50)
    pagina.insert_text((10, 30), "x")
    imagen = pagina.get_pixmap().tobytes("png")
    doc.close()
    return imagen


def pptx(textos: list[str] | None = None) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    presentacion = Presentation()
    for texto in textos or ["Diapositiva uno: el agente", "Diapositiva dos: resultados"]:
        diapositiva = presentacion.slides.add_slide(presentacion.slide_layouts[5])
        diapositiva.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text_frame.text = texto
    memoria = io.BytesIO()
    presentacion.save(memoria)
    return memoria.getvalue()
