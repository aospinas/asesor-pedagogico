// Panel de costos (RF-20): tokens y dólares por evaluación y en total. Los calcula el backend.
import { useEffect, useState } from "react";
import { ErrorApi, api, type Costos as TipoCostos } from "../../api";
import { Estado } from "../../componentes";
import { fecha } from "../../util";

const usd = (v: number) => `US$ ${v.toLocaleString("es-CO", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
const miles = (v: number) => v.toLocaleString("es-CO");

export default function Costos() {
  const [datos, setDatos] = useState<TipoCostos | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TipoCostos>("/api/costos?limite=200")
      .then(setDatos)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar el panel de costos."));
  }, []);

  if (!datos) return <Estado cargando={!error} error={error} />;
  const lista = datos.evaluaciones;
  const promedio = lista.length ? lista.reduce((s, e) => s + e.costo_usd, 0) / lista.length : null;

  return (
    <>
      <div className="cifras">
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Costo total</div>
          <div className="numero">{usd(datos.costo_usd)}</div>
        </div>
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Tokens de entrada</div>
          <div className="numero">{miles(datos.tokens_entrada)}</div>
        </div>
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Tokens de salida</div>
          <div className="numero">{miles(datos.tokens_salida)}</div>
        </div>
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Promedio por evaluación</div>
          <div className="numero">{promedio === null ? "—" : usd(promedio)}</div>
        </div>
      </div>
      <p className="secundario">
        Incluye los planes de mejora del informe: {usd(datos.planes_costo_usd)} ({miles(datos.planes_tokens_entrada)} tokens de
        entrada y {miles(datos.planes_tokens_salida)} de salida).
      </p>

      <h2>Por evaluación</h2>
      {datos.evaluaciones.length === 0 ? (
        <p className="secundario">Todavía no hay evaluaciones.</p>
      ) : (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Proveedor y modelo</th>
                <th>Tokens de entrada</th>
                <th>Tokens de salida</th>
                <th>Costo</th>
              </tr>
            </thead>
            <tbody>
              {datos.evaluaciones.map((e) => (
                <tr key={e.evaluacion_id}>
                  <td>{fecha(e.fecha)}</td>
                  <td>
                    {e.proveedor} · {e.modelo}
                  </td>
                  <td>{miles(e.tokens_entrada)}</td>
                  <td>{miles(e.tokens_salida)}</td>
                  <td>{usd(e.costo_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
