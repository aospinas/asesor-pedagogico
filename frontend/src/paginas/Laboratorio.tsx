import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ErrorApi,
  api,
  enviarJson,
  type Criterio,
  type Entrega,
  type Evaluacion,
  type Laboratorio as TipoLab,
  type RubricaEstructura,
  type RubricaVersion,
  type Usuario,
} from "../api";
import { Estado } from "../componentes";
import { ESTADO, fecha } from "../util";

const mensaje = (e: unknown) => (e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");

export default function Laboratorio() {
  const { id = "" } = useParams();
  const base = `/api/laboratorios/${encodeURIComponent(id)}`;
  const [lab, setLab] = useState<TipoLab | null>(null);
  const [versiones, setVersiones] = useState<RubricaVersion[]>([]);
  const [entregas, setEntregas] = useState<Entrega[]>([]);
  const [estudiantes, setEstudiantes] = useState<Usuario[]>([]);
  const [lanzadas, setLanzadas] = useState<Record<string, Evaluacion>>({});
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  function cargarRubrica() {
    api<RubricaVersion[]>(`${base}/rubrica/versiones`)
      .then(setVersiones)
      .catch(() => setVersiones([]));
  }

  useEffect(() => {
    api<TipoLab>(base)
      .then(setLab)
      .catch((e) => setError(mensaje(e)));
    cargarRubrica();
    api<Entrega[]>(`${base}/entregas`)
      .then(setEntregas)
      .catch(() => setEntregas([]));
    api<Usuario[]>("/api/estudiantes")
      .then(setEstudiantes)
      .catch(() => setEstudiantes([]));
  }, [base]);

  async function subirRubrica(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const forma = evento.currentTarget;
    setAviso("");
    setOcupado(true);
    try {
      await api(`${base}/rubrica`, { method: "POST", body: new FormData(forma) });
      forma.reset();
      setAviso("La IA convirtió la rúbrica. Revísala abajo y confírmala para poder evaluar.");
      cargarRubrica();
    } catch (e) {
      setAviso(mensaje(e));
    } finally {
      setOcupado(false);
    }
  }

  async function guardarRubrica(estructura: RubricaEstructura) {
    setAviso("");
    setOcupado(true);
    try {
      const v = await api<RubricaVersion>(`${base}/rubrica`, enviarJson(estructura, "PUT"));
      setAviso(v.valida ? `Rúbrica guardada como versión ${v.numero}.` : "Se guardó, pero todavía tiene errores.");
      cargarRubrica();
    } catch (e) {
      setAviso(mensaje(e));
    } finally {
      setOcupado(false);
    }
  }

  async function evaluar(entregaId: string) {
    setAviso("");
    setOcupado(true);
    try {
      const ev = await api<Evaluacion>(`/api/entregas/${entregaId}/evaluaciones`, { method: "POST" });
      setLanzadas((l) => ({ ...l, [entregaId]: ev }));
      setAviso("Evaluación en marcha. Cuando termine aparece en la bandeja.");
    } catch (e) {
      setAviso(mensaje(e));
    } finally {
      setOcupado(false);
    }
  }

  if (!lab) return <Estado cargando={!error} error={error} />;
  const vigente = versiones.length ? versiones.reduce((a, b) => (b.numero > a.numero ? b : a)) : null;
  const nombre = (eid: string) => estudiantes.find((e) => e.id === eid)?.nombre ?? "Estudiante";

  return (
    <>
      <p>
        <Link to="/laboratorios">← Volver a laboratorios</Link>
      </p>
      <h1>{lab.titulo}</h1>
      <p className="secundario">{lab.temas_ia.join(" · ")}</p>
      {aviso && (
        <p className="aviso" role="status">
          {aviso}
        </p>
      )}

      <h2>Rúbrica</h2>
      {vigente ? (
        <>
          <p>
            Versión {vigente.numero} · {fecha(vigente.fecha)} ·{" "}
            {vigente.por_confirmar ? (
              <span className="etiqueta alerta">Convertida por la IA: falta que la confirmes</span>
            ) : vigente.valida ? (
              <span className="etiqueta">Lista para evaluar</span>
            ) : (
              <span className="etiqueta rojo">Tiene errores</span>
            )}
          </p>
          {vigente.errores.length > 0 && (
            <ul className="error">
              {vigente.errores.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
          <Editor key={vigente.id} inicial={vigente.estructura} ocupado={ocupado} alGuardar={guardarRubrica} />
        </>
      ) : (
        <p className="secundario">Este laboratorio todavía no tiene rúbrica.</p>
      )}
      <form className="tarjeta" onSubmit={subirRubrica}>
        <label className="campo">
          {vigente ? "Reemplazar con otro archivo" : "Cargar rúbrica"}
          <span className="ayuda">PDF, Word (.docx), texto o JSON. La IA la convierte; tú la revisas y confirmas.</span>
          <input type="file" name="archivo" accept=".pdf,.docx,.txt,.md,.json" required />
        </label>
        <button className="boton" type="submit" disabled={ocupado}>
          {ocupado ? "Procesando…" : "Convertir con IA"}
        </button>
      </form>

      <h2>Entregas</h2>
      {entregas.length === 0 ? (
        <p className="secundario">Aún no hay entregas.</p>
      ) : (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Estudiante</th>
                <th>Fecha</th>
                <th>Archivos</th>
                <th>Evaluación</th>
              </tr>
            </thead>
            <tbody>
              {entregas.map((e) => {
                const ev = lanzadas[e.id];
                return (
                  <tr key={e.id}>
                    <td>{nombre(e.estudiante_id)}</td>
                    <td>{fecha(e.fecha)}</td>
                    <td>{e.evidencias.map((a) => a.nombre).join(", ")}</td>
                    <td>
                      {ev ? (
                        <Link to={`/revision/${ev.id}?laboratorio=${lab.id}`}>{ESTADO[ev.estado]}</Link>
                      ) : (
                        <button className="boton secundario" type="button" disabled={ocupado} onClick={() => evaluar(e.id)}>
                          Evaluar con IA
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** Editor sencillo de la rúbrica: nombres, pesos y niveles. Guardar crea una versión nueva. */
function Editor(props: { inicial: RubricaEstructura; ocupado: boolean; alGuardar: (r: RubricaEstructura) => void }) {
  const [rubrica, setRubrica] = useState<RubricaEstructura>(props.inicial);
  const suma = rubrica.criterios.reduce((s, c) => s + (Number(c.peso) || 0), 0);

  const cambiarCriterio = (i: number, cambio: Partial<Criterio>) =>
    setRubrica((r) => ({ ...r, criterios: r.criterios.map((c, j) => (j === i ? { ...c, ...cambio } : c)) }));

  return (
    <details className="tarjeta" open={false}>
      <summary>
        Ver y corregir la rúbrica ({rubrica.criterios.length} criterios, pesos que suman {suma} %)
      </summary>
      {rubrica.criterios.map((c, i) => (
        <fieldset key={c.id} className="tarjeta">
          <legend>
            Criterio {i + 1} <span className="secundario">({c.id})</span>
          </legend>
          <div className="rejilla">
            <label className="campo">
              Nombre
              <input value={c.nombre} maxLength={200} onChange={(e) => cambiarCriterio(i, { nombre: e.target.value })} />
            </label>
            <label className="campo">
              Competencia
              <input value={c.competencia} maxLength={200} onChange={(e) => cambiarCriterio(i, { competencia: e.target.value })} />
            </label>
            <label className="campo">
              Peso (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={c.peso}
                onChange={(e) => cambiarCriterio(i, { peso: Number(e.target.value) })}
              />
            </label>
          </div>
          {c.niveles.map((n, k) => (
            <div className="rejilla" key={n.id}>
              <label className="campo">
                Nivel
                <input
                  value={n.nombre}
                  maxLength={120}
                  onChange={(e) =>
                    cambiarCriterio(i, { niveles: c.niveles.map((m, z) => (z === k ? { ...m, nombre: e.target.value } : m)) })
                  }
                />
              </label>
              <label className="campo">
                Valor
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="any"
                  value={n.valor}
                  onChange={(e) =>
                    cambiarCriterio(i, {
                      niveles: c.niveles.map((m, z) => (z === k ? { ...m, valor: Number(e.target.value) } : m)),
                    })
                  }
                />
              </label>
              <label className="campo">
                Descriptor
                <input
                  value={n.descriptor}
                  maxLength={1000}
                  onChange={(e) =>
                    cambiarCriterio(i, {
                      niveles: c.niveles.map((m, z) => (z === k ? { ...m, descriptor: e.target.value } : m)),
                    })
                  }
                />
              </label>
            </div>
          ))}
        </fieldset>
      ))}
      {suma !== 100 && <p className="aviso">Los pesos deben sumar 100 % (ahora suman {suma} %).</p>}
      <button className="boton" type="button" disabled={props.ocupado} onClick={() => props.alGuardar(rubrica)}>
        Confirmar y guardar versión nueva
      </button>
    </details>
  );
}
