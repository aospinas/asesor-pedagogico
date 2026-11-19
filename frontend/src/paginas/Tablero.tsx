// Tablero del docente (D-24). Todos los números vienen calculados del backend (/api/tablero).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, type Tablero as TipoTablero } from "../api";
import { Barras, Cifra, Estado, Nivel } from "../componentes";
import { ICONO, coma, fecha, nivelDe } from "../util";

const PASOS = [
  { clave: "sin_evaluar", texto: "Sin evaluar", color: "#ffffff" },
  { clave: "en_proceso", texto: "La IA está evaluando", color: "#e7eeea" },
  { clave: "por_revisar", texto: "Por revisar", color: "#00b4d8" },
  { clave: "aprobadas", texto: "Aprobadas", color: "#8da197" },
  { clave: "publicadas", texto: "Publicadas", color: "#0b5d3b" },
] as const;

export default function Tablero() {
  const [datos, setDatos] = useState<TipoTablero | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TipoTablero>("/api/tablero")
      .then(setDatos)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar el tablero."));
  }, []);

  if (!datos) return <Estado cargando={!error} error={error} />;
  const { resumen, alertas, acuerdo } = datos;
  const totalAlertas = alertas.inyeccion + alertas.citas_no_encontradas + alertas.revision_manual;
  const maxNivel = Math.max(1, ...datos.niveles.map((n) => n.cantidad));

  return (
    <>
      <h1>Tablero del curso</h1>
      <p className="secundario">Datos reales al {fecha(datos.generado)}. Los calcula el sistema, no la IA.</p>

      <div className="cifras">
        <Dato titulo="Estudiantes" valor={resumen.estudiantes} />
        <Dato titulo="Laboratorios" valor={resumen.laboratorios} />
        <Dato titulo="Entregas" valor={resumen.entregas} />
        <Dato titulo="Por revisar" valor={resumen.por_revisar} enlace={resumen.por_revisar ? "/bandeja" : undefined} />
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Promedio publicado</div>
          <div className="numero">
            {resumen.promedio === null ? "—" : <Cifra valor={resumen.promedio} />}
          </div>
          {resumen.promedio !== null && <Nivel nivel={nivelDe(resumen.promedio)} />}
        </div>
      </div>

      {totalAlertas > 0 && (
        <section className="aviso" role="status">
          <strong>Para revisar con cuidado:</strong>{" "}
          {[
            alertas.inyeccion && `${alertas.inyeccion} con posible inyección de prompt`,
            alertas.citas_no_encontradas && `${alertas.citas_no_encontradas} con citas que no se encontraron`,
            alertas.revision_manual && `${alertas.revision_manual} en revisión manual`,
          ]
            .filter(Boolean)
            .join(" · ")}
          . <Link to="/bandeja">Ir a la bandeja</Link>
        </section>
      )}

      <h2>Dónde van las entregas</h2>
      {resumen.entregas === 0 ? (
        <p className="secundario">Todavía no hay entregas.</p>
      ) : (
        <>
          <div className="flujo" role="img" aria-label={PASOS.map((p) => `${p.texto}: ${resumen[p.clave]}`).join(", ")}>
            {PASOS.filter((p) => resumen[p.clave] > 0).map((p) => (
              <div key={p.clave} style={{ flexGrow: resumen[p.clave], background: p.color }} />
            ))}
          </div>
          <ul className="leyenda">
            {PASOS.map((p) => (
              <li key={p.clave}>
                <span className="muestra" style={{ background: p.color }} aria-hidden="true" /> {p.texto}: <strong>{resumen[p.clave]}</strong>
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="rejilla">
        <section>
          <h2>Niveles de las notas publicadas</h2>
          <div className="barras" role="list">
            {datos.niveles.map((n) => (
              <div className="barra-dominio" role="listitem" key={n.nivel}>
                <span>
                  <span aria-hidden="true">{ICONO[n.nivel]}</span> {n.nivel}
                </span>
                <div className="pista" aria-hidden="true">
                  <div className="relleno" style={{ width: `${(n.cantidad / maxNivel) * 100}%` }} />
                </div>
                <strong>{n.cantidad}</strong>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2>¿Cuánto cambia el docente lo que propone la IA?</h2>
          {acuerdo.porcentaje === null ? (
            <p className="secundario">Aparece cuando apruebes la primera evaluación.</p>
          ) : (
            <div className="tarjeta">
              <div className="numero">{coma(acuerdo.porcentaje)} %</div>
              <p>
                de los niveles quedaron como los propuso la IA. Cambiaste <strong>{acuerdo.cambiados}</strong> de{" "}
                {acuerdo.criterios}.
              </p>
              <p className="ayuda">La IA propone, el sistema calcula y tú decides: cada cambio queda en la traza.</p>
            </div>
          )}
        </section>
      </div>

      <h2>Criterios donde más cuesta</h2>
      {datos.criterios_debiles.length === 0 ? (
        <p className="secundario">Aparecen cuando haya evaluaciones aprobadas.</p>
      ) : (
        <Barras
          filas={datos.criterios_debiles.map((c) => ({
            nombre: `${c.criterio} · ${c.laboratorio} (${c.evaluaciones})`,
            promedio: c.promedio,
            nivel: c.nivel,
          }))}
        />
      )}

      <h2>Por laboratorio</h2>
      {datos.laboratorios.length === 0 ? (
        <p className="secundario">
          Aún no hay laboratorios. <Link to="/laboratorios">Crea el primero</Link>.
        </p>
      ) : (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Laboratorio</th>
                <th>Entregas</th>
                <th>Evaluadas</th>
                <th>Publicadas</th>
                <th>Promedio</th>
              </tr>
            </thead>
            <tbody>
              {datos.laboratorios.map((l) => (
                <tr key={l.laboratorio_id}>
                  <td>
                    <Link to={`/laboratorios/${l.laboratorio_id}`}>{l.titulo}</Link>
                  </td>
                  <td>{l.entregas}</td>
                  <td>{l.evaluadas}</td>
                  <td>{l.publicadas}</td>
                  <td>
                    {coma(l.promedio)} <Nivel nivel={l.nivel} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Dato({ titulo, valor, enlace }: { titulo: string; valor: number; enlace?: string }) {
  return (
    <div className="tarjeta cifra-tarjeta">
      <div className="secundario">{titulo}</div>
      <div className="numero">{valor}</div>
      {enlace && <Link to={enlace}>Abrir</Link>}
    </div>
  );
}
