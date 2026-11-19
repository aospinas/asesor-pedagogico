// Bitácora pública de uso de IA en el desarrollo (RF-22, D-26). Sale de docs/bitacora-ia.md.
import { useEffect, useState } from "react";
import { ErrorApi, api, type FilaBitacora } from "../api";
import { Estado } from "../componentes";

/** La bitácora usa `código` en Markdown: aquí se quitan las comillas invertidas y se deja texto plano. */
const limpio = (texto: string) => texto.replace(/`/g, "");

export default function Bitacora() {
  const [filas, setFilas] = useState<FilaBitacora[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ filas: FilaBitacora[] }>("/api/bitacora")
      .then((d) => setFilas(d.filas))
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la bitácora."));
  }, []);

  if (!filas) return <Estado cargando={!error} error={error} />;

  return (
    <>
      <h1>Bitácora de uso de IA</h1>
      <p className="secundario">
        Cómo usamos la IA para construir este proyecto: qué le pedimos, qué aportó, dónde falló y qué decidimos nosotros.
        Una fila por módulo ({filas.length} en total).
      </p>
      {filas.map((f, i) => (
        <details className="tarjeta" key={i} open={i === filas.length - 1}>
          <summary>
            <strong>{f.fase}</strong> <span className="secundario">· {f.fecha} · {limpio(f.herramienta)}</span>
          </summary>
          <dl className="bitacora">
            <dt>Qué se le pidió</dt>
            <dd>{limpio(f.pedido)}</dd>
            <dt>Qué aportó</dt>
            <dd>{limpio(f.aporte)}</dd>
            <dt>Problema o limitación</dt>
            <dd>{limpio(f.problema)}</dd>
            <dt>Decisión humana</dt>
            <dd>{limpio(f.decision)}</dd>
          </dl>
        </details>
      ))}
    </>
  );
}
