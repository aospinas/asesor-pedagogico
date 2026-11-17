"""Revisión docente: ajustar el nivel, aprobar y publicar (RF-14, CU-05)."""

import uuid

from datos_prueba import rubrica_de_prueba

from app.esquemas import RubricaEstructura
from app.evaluador.nota import calcular_nota
from app.modelos import Entrega, EvaluacionCriterio, Evidencia, VerificacionCodigoFila
from app.modelos import Evaluacion as EvaluacionFila


def sembrar(db, laboratorio, rubrica, estudiante, docente_id, niveles=("alto", "alto", "alto"), alerta=False):
    """Una evaluación ya terminada, lista para que el docente la revise."""
    entrega = Entrega(
        estudiante_id=estudiante.id,
        laboratorio_id=laboratorio.id,
        rubrica_version_id=rubrica.id,
        sha256_informe=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    db.add(entrega)
    db.flush()
    db.add(
        Evidencia(
            entrega_id=entrega.id,
            tipo="pdf",
            nombre="informe.pdf",
            sha256="ab" * 32,
            tamano_bytes=120,
            tipo_mime="application/pdf",
            ruta_storage=f"{entrega.id}/informe.pdf",
            resumen="2 páginas",
        )
    )
    rubrica_ok = RubricaEstructura.model_validate(rubrica_de_prueba())
    elegidos = {f"c{i}": nivel for i, nivel in enumerate(niveles, start=1) if nivel}
    nota = calcular_nota(rubrica_ok, elegidos) if len(elegidos) == 3 else None
    estado = "en_revision" if nota is not None else "revision_manual"
    evaluacion = EvaluacionFila(
        entrega_id=entrega.id,
        rubrica_version_id=rubrica.id,
        lanzada_por=docente_id,
        estado=estado,
        proveedor="openai",
        modelo="modelo-prueba",
        version_prompt="evaluar_criterio_v2",
        nota_preliminar=nota,
        tokens_entrada=12,
        tokens_salida=8,
        costo_usd=0.0,
        alerta_inyeccion=alerta,
    )
    db.add(evaluacion)
    db.flush()
    db.add(
        VerificacionCodigoFila(
            evaluacion_id=evaluacion.id,
            orden=0,
            tipo="sintaxis",
            comando="sintaxis",
            codigo_salida=0,
            salida="sin errores",
            duracion_ms=4,
            tiempo_agotado=False,
        )
    )
    for orden, nivel in enumerate(niveles, start=1):
        db.add(
            EvaluacionCriterio(
                evaluacion_id=evaluacion.id,
                criterio_id=f"c{orden}",
                orden=orden,
                nivel_ia=nivel,
                justificacion="La entrega lo muestra en el informe.",
                evidencias=[
                    {
                        "archivo": "informe.pdf",
                        "ubicacion": "página 1",
                        "fragmento": "El agente usa herramientas.",
                        "encontrada": True,
                    }
                ],
                fortalezas=["Usa herramientas"],
                debilidades=["Falta manejo de errores"],
                recomendaciones=["Agregar pruebas"],
            )
        )
    db.commit()
    return evaluacion


def test_al_cambiar_el_nivel_la_nota_se_recalcula(db, laboratorio, rubrica_lista, crear_usuario, entrar):
    estudiante = crear_usuario("estudiante", correo="est.rev@umanizales.edu.co")
    docente = entrar("docente", correo="docente.rev@umanizales.edu.co")
    evaluacion = sembrar(db, laboratorio, rubrica_lista, estudiante, docente.usuario.id)

    r = docente.post(
        f"/api/evaluaciones/{evaluacion.id}/ajustes",
        json={"criterio_id": "c1", "nivel_id": "bajo", "justificacion": "El manejo de errores no alcanza."},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["nota_final"] == 3.7
    assert cuerpo["nota_preliminar"] == 5.0
    criterio = next(c for c in cuerpo["criterios"] if c["criterio_id"] == "c1")
    assert criterio["nivel_final"] == "bajo"
    assert criterio["nivel_ia"] == "alto"


def test_el_estudiante_no_ve_nada_hasta_que_se_publica(db, laboratorio, rubrica_lista, entrar):
    docente = entrar("docente", correo="docente.pub@umanizales.edu.co")
    sesion = entrar("estudiante", correo="est.pub@umanizales.edu.co")
    ajeno = entrar("estudiante", correo="otro.pub@umanizales.edu.co")
    evaluacion = sembrar(db, laboratorio, rubrica_lista, sesion.usuario, docente.usuario.id)

    assert sesion.get(f"/api/evaluaciones/{evaluacion.id}").status_code == 403
    assert sesion.get(f"/api/evaluaciones/{evaluacion.id}/publicada").status_code == 404

    assert docente.post(f"/api/evaluaciones/{evaluacion.id}/publicar").status_code == 409
    aprobada = docente.post(f"/api/evaluaciones/{evaluacion.id}/aprobar")
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["estado"] == "aprobada"
    assert aprobada.json()["nota_final"] == 5.0
    assert sesion.get(f"/api/evaluaciones/{evaluacion.id}/publicada").status_code == 404

    publicada = docente.post(f"/api/evaluaciones/{evaluacion.id}/publicar")
    assert publicada.status_code == 200, publicada.text
    assert publicada.json()["estado"] == "publicada"
    assert (
        docente.post(
            f"/api/evaluaciones/{evaluacion.id}/ajustes",
            json={"criterio_id": "c1", "nivel_id": "bajo", "justificacion": "Demasiado tarde."},
        ).status_code
        == 409
    )

    vista = sesion.get(f"/api/evaluaciones/{evaluacion.id}/publicada")
    assert vista.status_code == 200, vista.text
    texto = vista.text
    assert "nivel_ia" not in texto
    assert "tokens_entrada" not in texto
    assert "modelo-prueba" not in texto
    assert vista.json()["nota_final"] == 5.0
    assert ajeno.get(f"/api/evaluaciones/{evaluacion.id}/publicada").status_code == 404


def test_sin_nivel_no_se_aprueba_y_al_ponerlo_pasa_a_revision(
    db, laboratorio, rubrica_lista, crear_usuario, entrar
):
    estudiante = crear_usuario("estudiante", correo="est.manual@umanizales.edu.co")
    docente = entrar("docente", correo="docente.manual@umanizales.edu.co")
    evaluacion = sembrar(
        db, laboratorio, rubrica_lista, estudiante, docente.usuario.id, niveles=("alto", "alto", None)
    )
    assert evaluacion.estado == "revision_manual"
    assert docente.post(f"/api/evaluaciones/{evaluacion.id}/aprobar").status_code == 409

    puesto = docente.post(
        f"/api/evaluaciones/{evaluacion.id}/ajustes",
        json={"criterio_id": "c3", "nivel_id": "medio", "justificacion": "Cumple una parte."},
    )
    assert puesto.status_code == 200, puesto.text
    assert puesto.json()["estado"] == "en_revision"
    assert puesto.json()["nota_final"] is not None
    assert docente.post(f"/api/evaluaciones/{evaluacion.id}/aprobar").status_code == 200


def test_un_nivel_inventado_no_se_guarda_ni_se_repite_en_el_mensaje(
    db, laboratorio, rubrica_lista, crear_usuario, entrar
):
    estudiante = crear_usuario("estudiante", correo="est.nivel@umanizales.edu.co")
    docente = entrar("docente", correo="docente.nivel@umanizales.edu.co")
    evaluacion = sembrar(db, laboratorio, rubrica_lista, estudiante, docente.usuario.id)
    r = docente.post(
        f"/api/evaluaciones/{evaluacion.id}/ajustes",
        json={"criterio_id": "c1", "nivel_id": "excelente-inventado", "justificacion": "No existe."},
    )
    assert r.status_code == 422
    assert "excelente-inventado" not in r.text


def test_la_bandeja_pone_primero_la_que_tiene_alerta(db, laboratorio, rubrica_lista, crear_usuario, entrar):
    estudiante = crear_usuario("estudiante", correo="est.banda@umanizales.edu.co")
    docente = entrar("docente", correo="docente.banda@umanizales.edu.co")
    normal = sembrar(db, laboratorio, rubrica_lista, estudiante, docente.usuario.id)
    urgente = sembrar(db, laboratorio, rubrica_lista, estudiante, docente.usuario.id, alerta=True)
    # La segunda entrega choca con el mismo informe si el sha se repite: sembrar usa uuid, así que no.
    del normal
    r = docente.get("/api/evaluaciones")
    assert r.status_code == 200, r.text
    ids = [fila["id"] for fila in r.json()]
    assert ids[0] == str(urgente.id)
    assert r.json()[0]["motivos"] == ["alerta_inyeccion"]
