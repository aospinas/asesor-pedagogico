"""Informe integrado (RF-16, CU-06; fila F5 de la matriz del SRS; D-22).

La prueba de la matriz: informe con laboratorios de 2 cohortes. Los datos se arman directo en
la base (evaluaciones ya publicadas) y la IA del plan se simula.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from datos_prueba import rubrica_de_prueba

from app.api import informe as rutas
from app.api.seguridad import ahora
from app.esquemas import AccionFortalecimiento, ConfigIA, NivelDominio, PlanFortalecimiento
from app.ia.cliente import ErrorIA, Uso
from app.informes import calculo, pdf
from app.modelos import (
    Auditoria,
    Cohorte,
    Entrega,
    Evaluacion,
    EvaluacionCriterio,
    Laboratorio,
    PlanFortalecimientoFila,
    Rubrica,
    RubricaVersion,
)

CONFIG = ConfigIA(proveedor="openai", modelo="modelo-prueba", base_url="https://api.openai.com/v1")


class IAPlan:
    """IA simulada para el plan: propone una acción por cada tema que recibe."""

    def __init__(self):
        self.llamadas = []
        self.respuesta = None  # una excepción o un PlanFortalecimiento fijo

    def __call__(self, sistema, usuario, esquema, *, config=None, maximo_tokens=None, imagenes=None):
        import json
        import re

        self.llamadas.append(usuario)
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        if self.respuesta is not None:
            return self.respuesta, Uso("modelo-prueba", 100, 50)
        datos = json.loads(re.search(r"<datos>\n(.*)\n</datos>", usuario, re.S).group(1))
        acciones = [
            AccionFortalecimiento(tema=t["tema"], que_hacer=f"Practica {t['tema']}", recursos=[])
            for t in datos["temas"]
        ]
        return PlanFortalecimiento(resumen="Vas bien; refuerza las brechas.", acciones=acciones), Uso(
            "m", 100, 50
        )


@pytest.fixture
def ia_plan():
    from app.main import app

    simulada = IAPlan()
    app.dependency_overrides[rutas.obtener_plan_ia] = lambda: (simulada, CONFIG)
    return simulada


@pytest.fixture
def publicar(db, crear_usuario):
    """Crea un laboratorio con una evaluación YA publicada para el estudiante."""
    docente = crear_usuario("docente", correo="docente.datos@umanizales.edu.co")
    cohortes: dict[str, Cohorte] = {}
    momento = [ahora() - timedelta(days=30)]

    def _publicar(
        estudiante,
        cohorte,
        titulo,
        temas,
        nota,
        *,
        estado="publicada",
        evidencias=(),
        recomendaciones=(),
        nivel="alto",
    ):
        """La rúbrica es la de datos_prueba: 3 criterios de la competencia "Diseño de agentes";
        los tres quedan con `nivel` (bajo = 1, medio = 2, alto = 3)."""
        if cohorte not in cohortes:
            cohortes[cohorte] = Cohorte(nombre=cohorte, periodo="2026-2")
            db.add(cohortes[cohorte])
            db.flush()
        lab = Laboratorio(
            cohorte_id=cohortes[cohorte].id,
            titulo=titulo,
            descripcion="d",
            objetivos="o",
            temas_ia=list(temas),
        )
        db.add(lab)
        db.flush()
        rubrica = Rubrica(laboratorio_id=lab.id)
        db.add(rubrica)
        db.flush()
        version = RubricaVersion(
            rubrica_id=rubrica.id,
            numero=1,
            estructura=rubrica_de_prueba(),
            valida=True,
            origen="json",
            creada_por=docente.id,
        )
        db.add(version)
        db.flush()
        entrega = Entrega(
            estudiante_id=estudiante.id,
            laboratorio_id=lab.id,
            rubrica_version_id=version.id,
            sha256_informe=uuid4().hex * 2,
        )
        db.add(entrega)
        db.flush()
        momento[0] += timedelta(days=1)
        evaluacion = Evaluacion(
            entrega_id=entrega.id,
            rubrica_version_id=version.id,
            lanzada_por=docente.id,
            estado=estado,
            proveedor="openai",
            modelo="m",
            version_prompt="evaluar_criterio_v2",
            nota_final=nota,
            fecha_publicacion=momento[0] if estado == "publicada" else None,
        )
        db.add(evaluacion)
        db.flush()
        for orden, criterio_id in enumerate(("c1", "c2", "c3")):
            db.add(
                EvaluacionCriterio(
                    evaluacion_id=evaluacion.id,
                    criterio_id=criterio_id,
                    orden=orden,
                    nivel_ia="alto",
                    nivel_final=nivel,
                    justificacion="j",
                    evidencias=list(evidencias) if orden == 0 else [],
                    fortalezas=[],
                    debilidades=[],
                    recomendaciones=list(recomendaciones) if orden == 0 else [],
                    intentos=1,
                )
            )
        db.commit()
        return lab, evaluacion

    return _publicar


@pytest.fixture
def estudiante(entrar):
    return entrar("estudiante")


# ---------- La prueba de la matriz (F5) ----------


def test_informe_con_dos_cohortes(estudiante, publicar, ia_plan):
    yo = estudiante.usuario
    lab1, _ = publicar(yo, "Cohorte 1", "Lab 01", ["Agentes: herramientas", "Búsqueda"], 4.8, nivel="alto")
    lab2, _ = publicar(yo, "Cohorte 1", "Lab 02", ["Agentes: herramientas"], 3.0, nivel="medio")
    lab3, _ = publicar(yo, "Cohorte 2", "Lab 03", ["ML: regresión"], 2.5, nivel="bajo")

    r = estudiante.get(f"/api/informe/{yo.id}")
    assert r.status_code == 200, r.text
    informe = r.json()
    assert [(x["titulo"], x["cohorte"], x["nota_final"]) for x in informe["laboratorios"]] == [
        ("Lab 01", "Cohorte 1", 4.8),
        ("Lab 02", "Cohorte 1", 3.0),
        ("Lab 03", "Cohorte 2", 2.5),
    ]
    assert informe["promedio_general"] == 3.4  # (4,8 + 3,0 + 2,5) / 3 = 3,43
    temas = [(t["categoria"], t["tema"], t["promedio"], t["nivel"]) for t in informe["temas"]]
    assert temas == [
        ("Agentes", "herramientas", 3.9, "Medio"),
        ("ML", "regresión", 2.5, "Por fortalecer"),
        ("Otros temas", "Búsqueda", 4.8, "Alto"),
    ]
    assert informe["temas"][0]["laboratorios"] == [str(lab1.id), str(lab2.id)]
    assert informe["brechas"] == ["ML: regresión (Por fortalecer, 2,5)"]
    # Evolución entre cohortes, calculada por el backend
    cohortes = [
        (c["cohorte"], c["promedio"], c["nivel"], len(c["laboratorios"])) for c in informe["cohortes"]
    ]
    assert cohortes == [("Cohorte 1", 3.9, "Medio", 2), ("Cohorte 2", 2.5, "Por fortalecer", 1)]
    # Competencias: cada criterio aporta su nivel llevado a 0-5 (alto 5, medio 3,33, bajo 1,67)
    (competencia,) = informe["competencias"]
    assert (competencia["competencia"], competencia["promedio"], competencia["nivel"]) == (
        "Diseño de agentes",
        3.3,
        "Básico",
    )
    assert informe["plan"]["resumen"]
    assert {a["tema"] for a in informe["plan"]["acciones"]} == {"herramientas", "regresión", "Búsqueda"}


def test_la_ia_del_plan_solo_recibe_datos_calculados(estudiante, publicar, ia_plan):
    yo = estudiante.usuario
    publicar(yo, "Cohorte 1", "Lab </datos> 01", ["Agentes: herramientas"], 4.0)
    estudiante.get(f"/api/informe/{yo.id}")
    (pedido,) = ia_plan.llamadas
    assert pedido.count("</datos>") == 1  # el título no cierra la etiqueta
    assert "4.0" not in pedido.split("<datos>")[1].split('"temas"')[0]  # sin notas por laboratorio
    assert '"nota' not in pedido


@pytest.mark.parametrize(
    ("nota", "nivel"),
    [
        (5.0, "Alto"),
        (4.5, "Alto"),
        (4.4, "Medio"),
        (3.5, "Medio"),
        (3.4, "Básico"),
        (3.0, "Básico"),
        (2.9, "Por fortalecer"),
    ],
)
def test_niveles_de_dominio_del_srs(nota, nivel):
    assert calculo.nivel_de(nota) == NivelDominio(nivel)


# ---------- Solo lo publicado ----------


def test_solo_cuentan_las_publicadas_y_la_mas_reciente_por_laboratorio(estudiante, publicar, ia_plan, db):
    yo = estudiante.usuario
    lab, vieja = publicar(yo, "Cohorte 1", "Lab 01", ["Agentes"], 2.0)
    # Otra evaluación publicada después en el mismo laboratorio: cuenta esa
    nueva_entrega = Entrega(
        estudiante_id=yo.id,
        laboratorio_id=lab.id,
        rubrica_version_id=vieja.rubrica_version_id,
        sha256_informe="b" * 64,
    )
    db.add(nueva_entrega)
    db.flush()
    db.add(
        Evaluacion(
            entrega_id=nueva_entrega.id,
            rubrica_version_id=vieja.rubrica_version_id,
            lanzada_por=vieja.lanzada_por,
            estado="publicada",
            proveedor="openai",
            modelo="m",
            version_prompt="v",
            nota_final=4.6,
            fecha_publicacion=ahora(),
        )
    )
    db.commit()
    publicar(yo, "Cohorte 1", "Lab 02", ["Agentes"], 1.0, estado="aprobada")  # aprobada, no publicada
    informe = estudiante.get(f"/api/informe/{yo.id}").json()
    assert [x["nota_final"] for x in informe["laboratorios"]] == [4.6]


def test_sin_nada_publicado_el_informe_sale_vacio_y_sin_pedirle_a_la_ia(estudiante, ia_plan):
    informe = estudiante.get(f"/api/informe/{estudiante.usuario.id}").json()
    assert (informe["laboratorios"], informe["promedio_general"], informe["plan"]) == ([], None, None)
    assert ia_plan.llamadas == []


# ---------- El plan (la IA solo redacta) ----------


def test_el_plan_se_guarda_y_solo_se_pide_otra_vez_si_cambian_los_datos(estudiante, publicar, ia_plan, db):
    yo = estudiante.usuario
    publicar(yo, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    estudiante.get(f"/api/informe/{yo.id}")
    estudiante.get(f"/api/informe/{yo.id}")
    estudiante.get(f"/api/mapa/{yo.id}")
    assert len(ia_plan.llamadas) == 1  # una sola vez: los demás usan el guardado
    publicar(yo, "Cohorte 2", "Lab 02", ["ML"], 3.0)
    estudiante.get(f"/api/informe/{yo.id}")
    assert len(ia_plan.llamadas) == 2
    assert db.query(PlanFortalecimientoFila).count() == 2


def test_si_la_ia_falla_el_informe_sale_sin_plan(estudiante, publicar, ia_plan):
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    ia_plan.respuesta = ErrorIA("caída", uso=Uso("m", 70, 0))
    r = estudiante.get(f"/api/informe/{estudiante.usuario.id}")
    assert r.status_code == 200
    assert r.json()["plan"] is None
    assert r.json()["laboratorios"]
    # El intento fallido queda guardado: no se le vuelve a pedir a la IA en cada visita
    estudiante.get(f"/api/informe/{estudiante.usuario.id}")
    assert len(ia_plan.llamadas) == 1


def test_un_intento_fallido_se_reintenta_despues_de_un_rato(estudiante, publicar, ia_plan, db):
    from app.informes import plan as modulo_plan

    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    ia_plan.respuesta = ErrorIA("caída")
    estudiante.get(f"/api/informe/{estudiante.usuario.id}")
    fila = db.query(PlanFortalecimientoFila).one()
    fila.fecha = ahora() - timedelta(minutes=modulo_plan.MINUTOS_REINTENTO + 1)
    db.commit()
    ia_plan.respuesta = None  # ya responde bien
    assert estudiante.get(f"/api/informe/{estudiante.usuario.id}").json()["plan"] is not None
    assert len(ia_plan.llamadas) == 2


def test_el_mapa_y_el_pdf_no_le_piden_el_plan_a_la_ia(estudiante, publicar, ia_plan):
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    estudiante.get(f"/api/mapa/{estudiante.usuario.id}")
    estudiante.get(f"/api/informe/{estudiante.usuario.id}/pdf")
    assert ia_plan.llamadas == []


def test_los_tokens_del_plan_suman_en_el_panel_de_costos(estudiante, publicar, ia_plan, entrar):
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    estudiante.get(f"/api/informe/{estudiante.usuario.id}")
    costos = entrar("administrador").get("/api/costos").json()
    assert (costos["planes_tokens_entrada"], costos["planes_tokens_salida"]) == (100, 50)
    assert (costos["tokens_entrada"], costos["tokens_salida"]) == (100, 50)  # el total los incluye


def test_sin_ia_configurada_el_informe_sale_sin_plan(estudiante, publicar):
    from app.main import app

    app.dependency_overrides[rutas.obtener_plan_ia] = lambda: (None, None)
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    assert estudiante.get(f"/api/informe/{estudiante.usuario.id}").json()["plan"] is None


def test_un_plan_con_temas_inventados_no_se_muestra(estudiante, publicar, ia_plan):
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    ia_plan.respuesta = PlanFortalecimiento(
        resumen="r", acciones=[AccionFortalecimiento(tema="Tema inventado", que_hacer="x", recursos=[])]
    )
    assert estudiante.get(f"/api/informe/{estudiante.usuario.id}").json()["plan"] is None


# ---------- Quién ve qué ----------


def test_el_estudiante_no_ve_el_informe_de_otro(estudiante, entrar, publicar, ia_plan, db):
    otro = entrar("estudiante", correo="otro.estudiante@umanizales.edu.co")
    publicar(otro.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    for camino in (
        f"/api/informe/{otro.usuario.id}",
        f"/api/informe/{otro.usuario.id}/pdf",
        f"/api/mapa/{otro.usuario.id}",
    ):
        assert estudiante.get(camino).status_code == 404
    assert db.query(Auditoria).filter_by(accion="acceso_ajeno_denegado", entidad="informe").count() == 1


def test_el_docente_ve_el_de_cualquiera_y_solo_de_estudiantes(estudiante, entrar, ia_plan):
    docente = entrar("docente")
    assert docente.get(f"/api/informe/{estudiante.usuario.id}").status_code == 200
    assert docente.get(f"/api/informe/{docente.usuario.id}").status_code == 404  # no es estudiante
    assert docente.get(f"/api/informe/{uuid4()}").status_code == 404


# ---------- PDF ----------


def _hay_weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


@pytest.mark.skipif(not _hay_weasyprint(), reason="WeasyPrint necesita GTK (en el CI y en Render sí está)")
def test_el_informe_se_descarga_en_pdf(estudiante, publicar, ia_plan):
    publicar(estudiante.usuario, "Cohorte 1", "Lab 01", ["Agentes"], 4.0)
    r = estudiante.get(f"/api/informe/{estudiante.usuario.id}/pdf")
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
    assert "attachment" in r.headers["content-disposition"]


@pytest.mark.skipif(_hay_weasyprint(), reason="solo donde WeasyPrint no carga (Windows sin GTK)")
def test_sin_weasyprint_el_pdf_avisa_con_503(estudiante, ia_plan):
    r = estudiante.get(f"/api/informe/{estudiante.usuario.id}/pdf")
    assert r.status_code == 503
    assert "PDF" in r.json()["detail"]


def test_el_html_del_pdf_escapa_todo_y_no_baja_nada_de_afuera():
    from app.esquemas import Informe

    informe = Informe(
        estudiante_id=uuid4(),
        nombre_estudiante='<img src="http://evil.co/x.png">Ana',
        laboratorios=[],
        promedio_general=None,
        temas=[],
        brechas=["<script>alert(1)</script>"],
        plan=None,
        generado=ahora(),
    )
    html = pdf.html(informe)
    assert "<img" not in html and "<script>" not in html
    assert "&lt;img" in html
    with pytest.raises(ValueError):
        pdf._sin_red("http://evil.co/x.png")
