import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

type Cita = { archivo: string; ubicacion: string; fragmento: string; encontrada: boolean | null };
type Criterio = {
  criterio_id: string;
  nivel_ia: string | null;
  nivel_final: string | null;
  justificacion: string;
  evidencias: Cita[];
  fortalezas: string[];
  debilidades: string[];
  recomendaciones: string[];
};
type Evaluacion = {
  id: string;
  entrega_id: string;
  rubrica_version_id: string;
  estado: string;
  nota_preliminar: number | null;
  nota_final: number | null;
  criterios: Criterio[];
  alerta_inyeccion: boolean;
  aviso: string | null;
};
type Nivel = { id: string; nombre: string };
type CriterioRubrica = { id: string; nombre: string; niveles: Nivel[] };

export default function Revision() {
  const { id } = useParams();
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null);
  const [nombres, setNombres] = useState<Record<string, CriterioRubrica>>({});
  const [textos, setTextos] = useState<Record<string, string>>({});
  const [traza, setTraza] = useState<string>("");
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function cargar() {
    const datos = await api<Evaluacion>(`/api/evaluaciones/${id}`);
    setEvaluacion(datos);
    const entrega = await api<{ laboratorio_id: string }>(`/api/entregas/${datos.entrega_id}`);
    const versiones = await api<{ id: string; estructura: { criterios: CriterioRubrica[] } }[]>(
      `/api/laboratorios/${entrega.laboratorio_id}/rubrica/versiones`,
    );
    const version = versiones.find((v) => v.id === datos.rubrica_version_id);
    const mapa: Record<string, CriterioRubrica> = {};
    for (const criterio of version?.estructura.criterios || []) mapa[criterio.id] = criterio;
    setNombres(mapa);
  }

  useEffect(() => {
    cargar().catch((e) => setError(e.message));
  }, [id]);

  async function guardarNivel(criterioId: string, nivelId: string) {
    const justificacion = (textos[criterioId] || "").trim();
    if (!justificacion) {
      setError("Escribe por qué eliges ese nivel.");
      return;
    }
    setOcupado(true);
    setError("");
    try {
      const nueva = await api<Evaluacion>(`/api/evaluaciones/${id}/ajustes`, {
        method: "POST",
        body: JSON.stringify({ criterio_id: criterioId, nivel_id: nivelId, justificacion }),
      });
      setEvaluacion(nueva);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setOcupado(false);
    }
  }

  async function accion(camino: string) {
    setOcupado(true);
    setError("");
    try {
      setEvaluacion(await api<Evaluacion>(`/api/evaluaciones/${id}/${camino}`, { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar.");
    } finally {
      setOcupado(false);
    }
  }

  async function verTraza() {
    const datos = await api<unknown>(`/api/evaluaciones/${id}/traza`);
    setTraza(JSON.stringify(datos, null, 2));
  }

  if (error && !evaluacion) return <p className="error">{error}</p>;
  if (!evaluacion) return <p>Cargando la evaluación…</p>;
  const nota = evaluacion.nota_final ?? evaluacion.nota_preliminar;
  const abierta = evaluacion.estado === "en_revision" || evaluacion.estado === "revision_manual";

  return (
    <>
      <p className="secundario">Nota preliminar {evaluacion.nota_preliminar ?? "—"}</p>
      <p className="nota" aria-label={`Nota ${nota ?? "sin calcular"}`}>
        {nota ?? "—"}
      </p>
      {evaluacion.aviso && <p className="aviso">{evaluacion.aviso}</p>}
      {evaluacion.alerta_inyeccion && (
        <p className="aviso">El material trae frases que parecen instrucciones para la IA. Revísalo.</p>
      )}
      {error && <p className="error">{error}</p>}
      {evaluacion.criterios.map((criterio) => {
        const info = nombres[criterio.criterio_id];
        const vigente = criterio.nivel_final || criterio.nivel_ia;
        return (
          <section className="tarjeta" key={criterio.criterio_id}>
            <h2>{info?.nombre || criterio.criterio_id}</h2>
            <p>{criterio.justificacion}</p>
            <div className="escalones" role="group" aria-label="Niveles">
              {(info?.niveles || []).map((nivel, i) => (
                <button
                  key={nivel.id}
                  className={`escalon ${nivel.id === criterio.nivel_ia ? "ia" : ""} ${
                    nivel.id === vigente ? "elegido" : ""
                  }`}
                  style={{ minHeight: 36 + i * 18 }}
                  disabled={!abierta || ocupado}
                  onClick={() => guardarNivel(criterio.criterio_id, nivel.id)}
                >
                  {nivel.nombre}
                  {nivel.id === criterio.nivel_ia ? " · propuso la IA" : ""}
                </button>
              ))}
            </div>
            {abierta && (
              <label className="campo">
                Por qué este nivel
                <textarea
                  value={textos[criterio.criterio_id] ?? ""}
                  onChange={(e) => setTextos({ ...textos, [criterio.criterio_id]: e.target.value })}
                />
              </label>
            )}
            <p>
              <strong>Fortalezas:</strong> {criterio.fortalezas.join(", ") || "—"}
            </p>
            <p>
              <strong>Por mejorar:</strong> {criterio.debilidades.join(", ") || "—"}
            </p>
            {criterio.evidencias.map((cita, i) => (
              <blockquote
                className={`cita ${cita.encontrada === false ? "no" : "si"}`}
                key={`${cita.archivo}-${i}`}
              >
                {cita.encontrada === false ? "No encontrada" : "Encontrada"} · {cita.archivo}, {cita.ubicacion}
                <br />“{cita.fragmento}”
              </blockquote>
            ))}
          </section>
        );
      })}
      <div className="fila">
        {abierta && (
          <button className="boton" disabled={ocupado} onClick={() => accion("aprobar")}>
            Aprobar
          </button>
        )}
        {evaluacion.estado === "aprobada" && (
          <button className="boton" disabled={ocupado} onClick={() => accion("publicar")}>
            Publicar
          </button>
        )}
        <button className="boton secundario" onClick={verTraza}>
          Ver traza
        </button>
      </div>
      {traza && (
        <pre className="tarjeta bitacora" aria-label="Traza de la evaluación">
          {traza}
        </pre>
      )}
    </>
  );
}
