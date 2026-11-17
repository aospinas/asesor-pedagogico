import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorApi, api, type EvaluacionPublicada, type RubricaPublica } from "../api";
import { Altimetro, Estado, Nivel } from "../componentes";
import { fecha, nivelDe } from "../util";

export default function Publicada() {
  const { id = "" } = useParams();
  const [evaluacion, setEvaluacion] = useState<EvaluacionPublicada | null>(null);
  const [rubrica, setRubrica] = useState<RubricaPublica | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<EvaluacionPublicada>(`/api/evaluaciones/${encodeURIComponent(id)}/publicada`)
      .then(async (e) => {
        setEvaluacion(e);
        setRubrica(await api<RubricaPublica>(`/api/laboratorios/${e.laboratorio_id}/rubrica`).catch(() => null));
      })
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la evaluación."));
  }, [id]);

  if (!evaluacion) return <Estado cargando={!error} error={error} />;

  const criterio = (cid: string) => rubrica?.estructura.criterios.find((c) => c.id === cid);
  return (
    <>
      <p>
        <Link to="/informe">← Volver a mi informe</Link>
      </p>
      <h1>{rubrica?.estructura.laboratorio ?? "Evaluación publicada"}</h1>
      <p className="secundario">Publicada el {fecha(evaluacion.fecha_publicacion)}</p>
      <section className="tarjeta">
        <Altimetro preliminar={null} final={evaluacion.nota_final} />
        <p>
          <Nivel nivel={nivelDe(evaluacion.nota_final)} />
        </p>
      </section>
      {evaluacion.criterios.map((c) => {
        const info = criterio(c.criterio_id);
        const nivel = info?.niveles.find((n) => n.id === c.nivel_id);
        return (
          <article className="tarjeta" key={c.criterio_id}>
            <h2 style={{ marginTop: 0 }}>{info?.nombre ?? c.criterio_id}</h2>
            <p>
              <span className="etiqueta">{nivel?.nombre ?? c.nivel_id}</span>{" "}
              {info && <span className="secundario">· pesa {info.peso} %</span>}
            </p>
            <p>{c.justificacion}</p>
            {c.evidencias.map((e, i) => (
              <blockquote className="cita" key={i}>
                «{e.fragmento}»
                <div className="donde">
                  {e.archivo} · {e.ubicacion}
                </div>
              </blockquote>
            ))}
            <Lista titulo="Lo que hiciste bien" items={c.fortalezas} />
            <Lista titulo="Lo que falta" items={c.debilidades} />
            <Lista titulo="Para mejorar" items={c.recomendaciones} />
          </article>
        );
      })}
    </>
  );
}

function Lista({ titulo, items }: { titulo: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <h3>{titulo}</h3>
      <ul>
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </>
  );
}
