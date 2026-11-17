"""Informe integrado en PDF (RF-16) con WeasyPrint, en los colores de Cordillera (D-06).

- Todo el texto va escapado (nombres, títulos y el plan que redactó la IA): nada se interpreta
  como HTML.
- WeasyPrint no baja nada de afuera (OWASP A10, SSRF): el `url_fetcher` rechaza toda dirección.
  La plantilla no usa imágenes ni fuentes externas.
- Uno a la vez: WeasyPrint puede usar decenas de MB y Render tiene 512 MB.
- En Windows sin GTK, WeasyPrint no carga: `PDFNoDisponible` (la ruta responde 503). En Render
  y en el CI (Linux, con las librerías del Dockerfile) sí funciona.
"""

import threading
from html import escape

from app.esquemas import Informe, NivelDominio
from app.informes.calculo import coma

ESPERA_TURNO_SEG = 20
_TURNO = threading.BoundedSemaphore(1)

COLORES_NIVEL = {
    NivelDominio.ALTO: ("#0B5D3B", "#FFFFFF"),
    NivelDominio.MEDIO: ("#DCEBE3", "#15241C"),
    NivelDominio.BASICO: ("#FFFFFF", "#0B5D3B"),
    NivelDominio.POR_FORTALECER: ("#FDF0EF", "#B42318"),
}

ESTILO = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "DejaVu Sans", sans-serif; color: #15241C; font-size: 10.5pt; }
h1 { color: #0B5D3B; font-size: 20pt; margin: 0 0 2mm; }
h2 { color: #0B5D3B; font-size: 13pt; border-bottom: 2px solid #00B4D8;
     padding-bottom: 1mm; margin-top: 8mm; }
.sub { color: #44564B; margin: 0 0 6mm; }
.promedio { font-size: 28pt; color: #0B5D3B; font-weight: bold; }
table { width: 100%; border-collapse: collapse; margin-top: 3mm; }
th, td { text-align: left; padding: 2mm; border-bottom: 1px solid #C7D2CB; vertical-align: top; }
th { color: #44564B; font-weight: normal; font-size: 9pt; }
.nivel { padding: 0.5mm 2mm; border-radius: 2mm; font-size: 9pt; border: 1px solid #0B5D3B; }
.vacio { color: #44564B; }
li { margin-bottom: 1.5mm; }
"""


NO_DISPONIBLE = "En este servidor no se puede generar el PDF."


class PDFNoDisponible(Exception):
    """WeasyPrint no está en este equipo o no hay turno."""


def disponible() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _sin_red(url: str, *args, **kwargs):
    """Ninguna dirección se baja (SSRF). Se usa como respaldo del URLFetcher de abajo."""
    raise ValueError("El informe no baja nada de internet.")


def _buscador_sin_red():
    """En WeasyPrint 70 el `url_fetcher` es una clase; sin protocolos permitidos no baja nada."""
    from weasyprint.urls import URLFetcher

    try:
        return URLFetcher(allowed_protocols=())
    except TypeError:  # otra versión de WeasyPrint: la función que siempre falla
        return _sin_red


def _nivel(nivel: NivelDominio) -> str:
    fondo, texto = COLORES_NIVEL[nivel]
    return f'<span class="nivel" style="background:{fondo};color:{texto}">{escape(nivel.value)}</span>'


def html(informe: Informe) -> str:
    e = escape
    filas_labs = "".join(
        f"<tr><td>{e(r.titulo)}</td><td>{e(r.cohorte)}</td><td>{coma(r.nota_final)}</td>"
        f"<td>{_nivel(r.nivel)}</td></tr>"
        for r in informe.laboratorios
    )
    filas_cohortes = "".join(
        f"<tr><td>{e(c.cohorte)}</td><td>{len(c.laboratorios)}</td><td>{coma(c.promedio)}</td>"
        f"<td>{_nivel(c.nivel)}</td></tr>"
        for c in informe.cohortes
    )
    filas_competencias = "".join(
        f"<tr><td>{e(c.competencia)}</td><td>{coma(c.promedio)}</td><td>{_nivel(c.nivel)}</td></tr>"
        for c in informe.competencias
    )
    filas_temas = "".join(
        f"<tr><td>{e(t.categoria)}</td><td>{e(t.tema)}</td><td>{coma(t.promedio)}</td>"
        f"<td>{_nivel(t.nivel)}</td></tr>"
        for t in informe.temas
    )
    brechas = "".join(f"<li>{e(b)}</li>" for b in informe.brechas) or '<p class="vacio">Sin brechas.</p>'
    if informe.plan:
        acciones = "".join(
            f"<li><strong>{e(a.tema)}:</strong> {e(a.que_hacer)}"
            + (f"<br><span class='vacio'>{e('; '.join(a.recursos))}</span>" if a.recursos else "")
            + "</li>"
            for a in informe.plan.acciones
        )
        plan = f"<p>{e(informe.plan.resumen)}</p><ol>{acciones}</ol>"
    else:
        plan = '<p class="vacio">El plan de fortalecimiento todavía no está disponible.</p>'
    promedio = coma(informe.promedio_general) if informe.promedio_general is not None else "—"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{ESTILO}</style></head><body>
<h1>Informe integrado</h1>
<p class="sub">{e(informe.nombre_estudiante)} · generado el {informe.generado:%d/%m/%Y}</p>
<p>Promedio general: <span class="promedio">{promedio}</span> / 5,0</p>
<h2>Laboratorios</h2>
<table><tr><th>Laboratorio</th><th>Cohorte</th><th>Nota</th><th>Nivel</th></tr>{filas_labs}</table>
<h2>Evolución por cohorte</h2>
<table><tr><th>Cohorte</th><th>Laboratorios</th><th>Promedio</th><th>Nivel</th></tr>{filas_cohortes}</table>
<h2>Competencias</h2>
<table><tr><th>Competencia</th><th>Dominio</th><th>Nivel</th></tr>{filas_competencias}</table>
<h2>Dominio por tema</h2>
<table><tr><th>Categoría</th><th>Tema</th><th>Promedio</th><th>Nivel</th></tr>{filas_temas}</table>
<h2>Brechas</h2><ul>{brechas}</ul>
<h2>Plan de fortalecimiento</h2>{plan}
</body></html>"""


def generar(informe: Informe) -> bytes:
    try:
        from weasyprint import HTML  # se importa aquí: en Windows sin GTK no carga
    except (ImportError, OSError) as error:
        raise PDFNoDisponible(NO_DISPONIBLE) from error
    if not _TURNO.acquire(timeout=ESPERA_TURNO_SEG):
        raise PDFNoDisponible("Se está generando otro informe. Intenta en un momento.")
    try:
        return HTML(string=html(informe), url_fetcher=_buscador_sin_red()).write_pdf()
    finally:
        _TURNO.release()
