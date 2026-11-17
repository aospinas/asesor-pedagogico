"""Informe integrado y mapa mental a partir de lo ya publicado (RF-16, RF-17).

Los números salen de app/evaluador/nota.py. La IA, si está, solo redacta el plan.
"""

import html
import uuid
from collections import defaultdict
from functools import cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.seguridad import ahora, con_zona
from app.esquemas import (
    AristaMapa,
    DominioTema,
    Evidencia,
    Informe,
    MapaMental,
    NivelDominio,
    NodoMapa,
    PlanFortalecimiento,
    ResultadoLaboratorio,
    RubricaEstructura,
    TipoNodo,
)
from app.evaluador.nota import nivel_de_dominio, promedio
from app.modelos import Cohorte, Entrega, EvaluacionCriterio, Laboratorio, RubricaVersion, Usuario
from app.modelos import Evaluacion as EvaluacionFila

_PUBLICADA = "publicada"


def _ultima_por_laboratorio(
    db: Session, estudiante_id: uuid.UUID
) -> list[tuple[EvaluacionFila, Entrega, Laboratorio, Cohorte]]:
    filas = db.execute(
        select(EvaluacionFila, Entrega, Laboratorio, Cohorte)
        .join(Entrega, Entrega.id == EvaluacionFila.entrega_id)
        .join(Laboratorio, Laboratorio.id == Entrega.laboratorio_id)
        .join(Cohorte, Cohorte.id == Laboratorio.cohorte_id)
        .where(Entrega.estudiante_id == estudiante_id, EvaluacionFila.estado == _PUBLICADA)
        .order_by(EvaluacionFila.fecha_publicacion.desc(), EvaluacionFila.id.desc())
    ).all()
    vistos: set[uuid.UUID] = set()
    unicas = []
    for evaluacion, entrega, laboratorio, cohorte in filas:
        if laboratorio.id in vistos or evaluacion.nota_final is None:
            continue
        vistos.add(laboratorio.id)
        unicas.append((evaluacion, entrega, laboratorio, cohorte))
    unicas.sort(key=lambda fila: (fila[3].nombre, fila[3].periodo, str(fila[2].id)))
    return unicas


def _temas(laboratorio: Laboratorio, version: RubricaVersion | None) -> list[tuple[str, str]]:
    if laboratorio.temas_ia:
        return [("Temas del laboratorio", tema) for tema in laboratorio.temas_ia if tema]
    if version is not None:
        rubrica = RubricaEstructura.model_validate(version.estructura)
        competencias = list(dict.fromkeys(c.competencia for c in rubrica.criterios))
        if competencias:
            return [("Competencias", nombre) for nombre in competencias]
    return [("Temas del laboratorio", laboratorio.titulo)]


def _debilidades(db: Session, evaluacion_id: uuid.UUID) -> list[str]:
    textos: list[str] = []
    filas = db.scalars(select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id == evaluacion_id))
    for fila in filas:
        textos.extend(fila.debilidades)
    return textos


def _citas(db: Session, evaluacion_id: uuid.UUID) -> list[Evidencia]:
    citas: list[Evidencia] = []
    filas = db.scalars(select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id == evaluacion_id))
    for fila in filas:
        for dato in fila.evidencias:
            try:
                citas.append(
                    Evidencia.model_validate(
                        {
                            "archivo": dato.get("archivo"),
                            "ubicacion": dato.get("ubicacion"),
                            "fragmento": dato.get("fragmento"),
                        }
                    )
                )
            except ValueError:
                continue
            if len(citas) >= 3:
                return citas
    return citas


def armar_informe(
    db: Session,
    estudiante: Usuario,
    plan: PlanFortalecimiento | None = None,
) -> Informe:
    filas = _ultima_por_laboratorio(db, estudiante.id)
    resultados = [
        ResultadoLaboratorio(
            laboratorio_id=laboratorio.id,
            evaluacion_id=evaluacion.id,
            titulo=laboratorio.titulo,
            cohorte=f"{cohorte.nombre} · {cohorte.periodo}",
            nota_final=evaluacion.nota_final,
            nivel=nivel_de_dominio(evaluacion.nota_final),
            fecha_publicacion=con_zona(evaluacion.fecha_publicacion),
        )
        for evaluacion, _entrega, laboratorio, cohorte in filas
    ]
    notas = [r.nota_final for r in resultados]
    temas = _dominios(db, filas)
    brechas = [f"{tema.tema} ({tema.nivel.value})" for tema in temas if tema.nivel != NivelDominio.ALTO]
    return Informe(
        estudiante_id=estudiante.id,
        nombre_estudiante=estudiante.nombre,
        laboratorios=resultados,
        promedio_general=promedio(notas),
        temas=temas,
        brechas=brechas,
        plan=plan,
        generado=(con_zona(filas[0][0].fecha_publicacion) if filas else None) or ahora(),
    )


def _dominios(db: Session, filas: list[tuple]) -> list[DominioTema]:
    grupos: dict[tuple[str, str], list[tuple[float, uuid.UUID, uuid.UUID]]] = defaultdict(list)
    versiones = {
        evaluacion.rubrica_version_id: db.get(RubricaVersion, evaluacion.rubrica_version_id)
        for evaluacion, _e, _l, _c in filas
    }
    for evaluacion, _entrega, laboratorio, _cohorte in filas:
        for categoria, tema in _temas(laboratorio, versiones.get(evaluacion.rubrica_version_id)):
            grupos[(categoria, tema)].append((evaluacion.nota_final, laboratorio.id, evaluacion.id))
    dominios = []
    for (categoria, tema), datos in grupos.items():
        nota = promedio([nota for nota, _lab, _ev in datos]) or 0.0
        labs = list(dict.fromkeys(lab for _nota, lab, _ev in datos))
        dominios.append(
            DominioTema(
                categoria=categoria,
                tema=tema,
                promedio=nota,
                nivel=nivel_de_dominio(nota),
                laboratorios=labs,
            )
        )
    dominios.sort(key=lambda d: (d.categoria, d.tema))
    return dominios


def armar_mapa(db: Session, estudiante_id: uuid.UUID) -> MapaMental:
    filas = _ultima_por_laboratorio(db, estudiante_id)
    temas = _dominios(db, filas)
    nodos: list[NodoMapa] = []
    aristas: list[AristaMapa] = []
    categorias: dict[str, str] = {}
    for indice, tema in enumerate(temas):
        if tema.categoria not in categorias:
            categorias[tema.categoria] = f"cat-{len(categorias) + 1}"
            nodos.append(
                NodoMapa(id=categorias[tema.categoria], tipo=TipoNodo.CATEGORIA, etiqueta=tema.categoria)
            )
        tema_id = f"tema-{indice + 1}"
        debilidades: list[str] = []
        citas: list[Evidencia] = []
        for _evaluacion, _entrega, laboratorio, _cohorte in filas:
            if laboratorio.id not in tema.laboratorios:
                continue
            debilidades.extend(_debilidades(db, _evaluacion.id))
            if len(citas) < 3:
                citas.extend(_citas(db, _evaluacion.id))
        profundizar = []
        if tema.nivel in {NivelDominio.POR_FORTALECER, NivelDominio.BASICO}:
            profundizar.append(f"Profundizar: {tema.tema}")
        profundizar.extend(debilidades[:2])
        nodos.append(
            NodoMapa(
                id=tema_id,
                tipo=TipoNodo.TEMA,
                etiqueta=tema.tema,
                nivel=tema.nivel,
                evidencias=citas[:3],
                que_profundizar=profundizar[:3],
            )
        )
        aristas.append(AristaMapa(origen=categorias[tema.categoria], destino=tema_id))
        for laboratorio_id in tema.laboratorios:
            lab_id = f"lab-{laboratorio_id}"
            if not any(n.id == lab_id for n in nodos):
                laboratorio = db.get(Laboratorio, laboratorio_id)
                nodos.append(
                    NodoMapa(
                        id=lab_id,
                        tipo=TipoNodo.LABORATORIO,
                        etiqueta=laboratorio.titulo if laboratorio else "Laboratorio",
                    )
                )
            aristas.append(AristaMapa(origen=tema_id, destino=lab_id))
    return MapaMental(estudiante_id=estudiante_id, nodos=nodos, aristas=aristas)


def html_informe(informe: Informe) -> str:
    """HTML del informe, listo para imprimir o para WeasyPrint."""
    filas = "".join(
        "<tr>"
        f"<td>{html.escape(lab.cohorte)}</td>"
        f"<td>{html.escape(lab.titulo)}</td>"
        f"<td>{lab.nota_final:.1f}</td>"
        f"<td>{html.escape(lab.nivel.value)}</td>"
        "</tr>"
        for lab in informe.laboratorios
    )
    temas = "".join(
        f"<li>{html.escape(tema.tema)}: {html.escape(tema.nivel.value)} ({tema.promedio:.1f})</li>"
        for tema in informe.temas
    )
    brechas = (
        "".join(f"<li>{html.escape(b)}</li>" for b in informe.brechas) or "<li>Ninguna brecha marcada.</li>"
    )
    plan = ""
    if informe.plan is not None:
        acciones = "".join(
            f"<li><strong>{html.escape(a.tema)}.</strong> {html.escape(a.que_hacer)}</li>"
            for a in informe.plan.acciones
        )
        plan = (
            f"<h2>Plan de fortalecimiento</h2><p>{html.escape(informe.plan.resumen)}</p><ul>{acciones}</ul>"
        )
    promedio_txt = f"{informe.promedio_general:.1f}" if informe.promedio_general is not None else "—"
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe de {html.escape(informe.nombre_estudiante)}</title>
<style>
  body {{ font-family: "DejaVu Sans", sans-serif; color: #15241C; margin: 32px; }}
  h1 {{ color: #0B5D3B; font-size: 22px; }}
  .nota {{ font-size: 28px; color: #0B5D3B; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #C7D2CB; padding: 6px 8px; text-align: left; }}
  th {{ background: #E7EEEA; }}
</style>
</head>
<body>
  <h1>Informe de aprendizaje</h1>
  <p>{html.escape(informe.nombre_estudiante)}</p>
  <p class="nota">Promedio {promedio_txt}</p>
  <table>
    <thead><tr><th>Cohorte</th><th>Laboratorio</th><th>Nota</th><th>Dominio</th></tr></thead>
    <tbody>{filas}</tbody>
  </table>
  <h2>Temas</h2>
  <ul>{temas}</ul>
  <h2>Brechas</h2>
  <ul>{brechas}</ul>
  {plan}
</body>
</html>
"""


@cache
def _weasyprint_listo() -> bool:
    """WeasyPrint necesita librerías del sistema (en Docker sí están; en Windows a veces no)."""
    try:
        from weasyprint import HTML

        HTML(string="<p>ok</p>").write_pdf()
    except (OSError, ImportError):
        return False
    return True


def _pdf_simple(informe: Informe) -> bytes:
    """PDF de respaldo, sin librerías del sistema. El texto es el mismo que el de WeasyPrint."""
    import pymupdf

    lineas = ["Informe de aprendizaje", informe.nombre_estudiante, ""]
    if informe.promedio_general is None:
        lineas.append("Todavía no hay notas publicadas.")
    else:
        lineas.append(f"Promedio {informe.promedio_general:.1f}")
    lineas.append("")
    for lab in informe.laboratorios:
        lineas.append(f"{lab.cohorte} | {lab.titulo} | {lab.nota_final:.1f} | {lab.nivel.value}")
    for tema in informe.temas:
        lineas.append(f"Tema {tema.tema}: {tema.nivel.value}")
    for brecha in informe.brechas:
        lineas.append(f"Brecha: {brecha}")
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_textbox(pymupdf.Rect(40, 40, 555, 800), "\n".join(lineas), fontsize=11, fontname="helv")
    datos = documento.tobytes()
    documento.close()
    return datos


def pdf_informe(informe: Informe) -> bytes:
    if _weasyprint_listo():
        from weasyprint import HTML

        return HTML(string=html_informe(informe)).write_pdf()
    return _pdf_simple(informe)
