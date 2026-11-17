import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, type Informe as TipoInforme } from "../api";
import { Barras, Estado, Nivel, Perfil } from "../componentes";
import { coma, descargar, fecha, nivelDe } from "../util";

export default function Informe({ estudianteId }: { estudianteId: string }) {
  const [informe, setInforme] = useState<TipoInforme | null>(null);
  const [error, setError] = useState("");
  const [bajando, setBajando] = useState(false);
  const [errorPdf, setErrorPdf] = useState("");

  useEffect(() => {
    api<TipoInforme>(`/api/informe/${estudianteId}`)
      .then(setInforme)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar el informe."));
  }, [estudianteId]);

  async function pdf() {
    setErrorPdf("");
    setBajando(true);
    try {
      descargar(await api<Blob>(`/api/informe/${estudianteId}/pdf`), "informe.pdf");
    } catch (e) {
      setErrorPdf(e instanceof ErrorApi ? e.message : "No se pudo descargar el PDF.");
    } finally {
      setBajando(false);
    }
  }

  if (!informe) return <Estado cargando={!error} error={error} />;
  const labs = informe.laboratorios;

  return (
    <>
      <h1>Mi informe</h1>
      <p className="secundario">
        {informe.nombre_estudiante} · generado el {fecha(informe.generado)}
      </p>
      {labs.length === 0 ? (
        <p className="aviso">Aún no tienes evaluaciones publicadas. Cuando el docente publique una, aparece aquí.</p>
      ) : (
        <>
          <section className="tarjeta">
            <div className="fila" style={{ justifyContent: "space-between" }}>
              <div>
                <div className="secundario">Promedio general</div>
                <div className="altimetro">
                  <span className="cifra">{coma(informe.promedio_general)}</span>
                  <span className="de">de 5,0</span>
                </div>
              </div>
              {informe.promedio_general !== null && <Nivel nivel={nivelDe(informe.promedio_general)} />}
              <div className="fila">
                <button className="boton secundario" type="button" onClick={pdf} disabled={bajando}>
                  {bajando ? "Preparando PDF…" : "Descargar PDF"}
                </button>
                <Link className="boton secundario" to="/mapa">
                  Ver mapa mental
                </Link>
              </div>
            </div>
            {errorPdf && <p className="aviso">{errorPdf}</p>}
          </section>

          <h2>Perfil de ascenso</h2>
          <Perfil puntos={labs.map((l) => l.nota_final)} etiquetas={labs.map((l) => l.titulo)} />

          <h2>Laboratorios</h2>
          <div className="tabla-scroll">
            <table>
              <thead>
                <tr>
                  <th>Laboratorio</th>
                  <th>Cohorte</th>
                  <th>Nota</th>
                  <th>Nivel</th>
                  <th>Publicada</th>
                </tr>
              </thead>
              <tbody>
                {labs.map((l) => (
                  <tr key={l.evaluacion_id}>
                    <td>
                      <Link to={`/publicada/${l.evaluacion_id}`}>{l.titulo}</Link>
                    </td>
                    <td>{l.cohorte}</td>
                    <td>{coma(l.nota_final)}</td>
                    <td>
                      <Nivel nivel={l.nivel} />
                    </td>
                    <td>{fecha(l.fecha_publicacion)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {informe.competencias.length > 0 && (
            <>
              <h2>Por competencia</h2>
              <Barras filas={informe.competencias.map((c) => ({ nombre: c.competencia, ...c }))} />
            </>
          )}
          {informe.temas.length > 0 && (
            <>
              <h2>Por tema de IA</h2>
              <Barras filas={informe.temas.map((t) => ({ nombre: `${t.categoria}: ${t.tema}`, ...t }))} />
            </>
          )}
          {informe.cohortes.length > 1 && (
            <>
              <h2>Por cohorte</h2>
              <Barras filas={informe.cohortes.map((c) => ({ nombre: c.cohorte, ...c }))} />
            </>
          )}

          {informe.brechas.length > 0 && (
            <>
              <h2>Temas por fortalecer</h2>
              <ul>
                {informe.brechas.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </>
          )}

          <h2>Plan para seguir subiendo</h2>
          {informe.plan ? (
            <section className="tarjeta">
              <p>{informe.plan.resumen}</p>
              {informe.plan.acciones.map((a, i) => (
                <div key={i} style={{ marginTop: 12 }}>
                  <h3>{a.tema}</h3>
                  <p>{a.que_hacer}</p>
                  {a.recursos.length > 0 && (
                    <ul>
                      {a.recursos.map((r, j) => (
                        <li key={j}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
              <p className="ayuda">Este plan lo propone la IA a partir de tus notas; las notas las calcula el sistema.</p>
            </section>
          ) : (
            <p className="secundario">El plan todavía no está listo. Vuelve a abrir el informe en un rato.</p>
          )}
        </>
      )}
    </>
  );
}
