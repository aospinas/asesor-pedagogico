import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ErrorApi,
  api,
  enviarJson,
  type Criterio,
  type CriterioEvaluado,
  type Evaluacion,
  type RubricaVersion,
  type Traza,
} from "../api";
import { Altimetro, Estado } from "../componentes";
import { ESTADO, MOTIVO, fecha } from "../util";

const ACCION = {
  ajustar_nivel: "Cambió el nivel",
  editar_retroalimentacion: "Editó la retroalimentación",
  aprobar: "Aprobó",
  publicar: "Publicó",
};
const VERIFICACION = { sintaxis: "Sintaxis", estatico: "Revisión estática", pruebas: "Pruebas" };

const lineas = (texto: string) =>
  texto
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

const mensaje = (e: unknown) => (e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");

export default function Revision() {
  const { id = "" } = useParams();
  const [parametros] = useSearchParams();
  const laboratorio = parametros.get("laboratorio") ?? "";
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null);
  const [rubrica, setRubrica] = useState<RubricaVersion | null>(null);
  const [traza, setTraza] = useState<Traza | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const ruta = `/api/evaluaciones/${encodeURIComponent(id)}`;

  useEffect(() => {
    api<Evaluacion>(ruta)
      .then(async (e) => {
        setEvaluacion(e);
        if (laboratorio) {
          const versiones = await api<RubricaVersion[]>(
            `/api/laboratorios/${encodeURIComponent(laboratorio)}/rubrica/versiones`,
          ).catch(() => []);
          setRubrica(versiones.find((v) => v.id === e.rubrica_version_id) ?? null);
        }
      })
      .catch((e) => setError(mensaje(e)));
  }, [ruta, laboratorio]);

  async function accion(camino: string, opciones: RequestInit, listo: string) {
    setAviso("");
    setOcupado(true);
    try {
      setEvaluacion(await api<Evaluacion>(`${ruta}/${camino}`, opciones));
      setAviso(listo);
      setTraza(null);
      return true;
    } catch (e) {
      setAviso(mensaje(e));
      return false;
    } finally {
      setOcupado(false);
    }
  }

  async function verTraza() {
    try {
      setTraza(await api<Traza>(`${ruta}/traza`));
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  if (!evaluacion) return <Estado cargando={!error} error={error} />;

  const editable = evaluacion.estado === "en_revision" || evaluacion.estado === "revision_manual";
  const porId = new Map(evaluacion.criterios.map((c) => [c.criterio_id, c]));
  // Los criterios salen de la rúbrica: así aparecen también los que la IA no alcanzó a proponer.
  const criterios: { info: Criterio | null; datos: CriterioEvaluado | null; id: string }[] = rubrica
    ? rubrica.estructura.criterios.map((c) => ({ info: c, datos: porId.get(c.id) ?? null, id: c.id }))
    : evaluacion.criterios.map((c) => ({ info: null, datos: c, id: c.criterio_id }));

  return (
    <>
      <p>
        <Link to="/bandeja">← Volver a la bandeja</Link>
      </p>
      <h1>{rubrica?.estructura.laboratorio ?? "Revisión"}</h1>
      <p className="secundario">
        {ESTADO[evaluacion.estado]} · {fecha(evaluacion.fecha)} · {evaluacion.modelo} ({evaluacion.version_prompt})
      </p>
      {!rubrica && (
        <p className="aviso">No se pudo cargar la rúbrica: se muestran solo los criterios que propuso la IA.</p>
      )}
      {evaluacion.alerta_inyeccion && (
        <p className="error" role="alert">
          Posible inyección de prompt: la entrega trae texto que intenta darle órdenes a la IA. Revisa con cuidado.
        </p>
      )}
      {evaluacion.aviso && <p className="aviso">{evaluacion.aviso}</p>}
      {evaluacion.motivos.length > 0 && (
        <p>
          {evaluacion.motivos.map((m) => (
            <span key={m} className={`etiqueta ${m === "alerta_inyeccion" ? "rojo" : "alerta"}`} style={{ marginRight: 4 }}>
              {MOTIVO[m]}
            </span>
          ))}
        </p>
      )}

      <section className="tarjeta">
        <Altimetro preliminar={evaluacion.nota_preliminar} final={evaluacion.nota_final} />
        <p className="ayuda">La nota la calcula el sistema con los niveles y los pesos de la rúbrica; la IA nunca pone nota.</p>
        <div className="fila">
          {editable && (
            <button
              className="boton"
              type="button"
              disabled={ocupado || evaluacion.estado !== "en_revision"}
              onClick={() => accion("aprobar", { method: "POST" }, "Evaluación aprobada. Ya no se puede cambiar.")}
            >
              Aprobar
            </button>
          )}
          {evaluacion.estado === "aprobada" && (
            <button
              className="boton"
              type="button"
              disabled={ocupado}
              onClick={() => accion("publicar", { method: "POST" }, "Publicada: el estudiante ya la puede ver.")}
            >
              Publicar al estudiante
            </button>
          )}
        </div>
        {evaluacion.estado === "revision_manual" && (
          <p className="ayuda">Pon un nivel en cada criterio que falte para poder aprobar.</p>
        )}
        {aviso && (
          <p className="aviso" role="status">
            {aviso}
          </p>
        )}
      </section>

      {criterios.map((c) => (
        <TarjetaCriterio
          key={c.id}
          id={c.id}
          info={c.info}
          datos={c.datos}
          editable={editable && !ocupado}
          alAjustar={(nivel, justificacion) =>
            accion("ajustes", enviarJson({ criterio_id: c.id, nivel_id: nivel, justificacion }), "Nivel cambiado; la nota se recalculó.")
          }
          alRetro={(cuerpo) =>
            accion("retroalimentacion", enviarJson({ criterio_id: c.id, ...cuerpo }, "PATCH"), "Retroalimentación guardada.")
          }
        />
      ))}

      {evaluacion.verificaciones.length > 0 && (
        <>
          <h2>Verificación del código (sandbox)</h2>
          {evaluacion.verificaciones.map((v, i) => (
            <details className="tarjeta" key={i}>
              <summary>
                {VERIFICACION[v.tipo]}:{" "}
                {v.tiempo_agotado ? "se pasó del tiempo" : v.codigo_salida === 0 ? "sin errores" : `salió con código ${v.codigo_salida ?? "—"}`}{" "}
                <span className="secundario">· {v.duracion_ms} ms</span>
              </summary>
              <p className="secundario">
                <code>{v.comando}</code>
              </p>
              <pre className="salida">{v.salida || "(sin salida)"}</pre>
            </details>
          ))}
        </>
      )}

      <h2>Traza</h2>
      {traza ? (
        <section className="tarjeta">
          <p>
            {traza.proveedor} · {traza.modelo} · prompt {traza.version_prompt} · {traza.tokens_entrada} tokens de entrada y{" "}
            {traza.tokens_salida} de salida
          </p>
          <p className="secundario">
            Evaluada el {fecha(traza.fecha)} · aprobada {fecha(traza.fecha_aprobacion)} · publicada {fecha(traza.fecha_publicacion)}
          </p>
          <h3>Archivos</h3>
          <ul>
            {traza.evidencias.map((e) => (
              <li key={e.id}>
                {e.nombre} <span className="secundario">· huella {e.sha256.slice(0, 12)}…</span>
              </li>
            ))}
          </ul>
          <h3>Cambios del docente</h3>
          {traza.revisiones.length === 0 ? (
            <p className="secundario">Sin cambios.</p>
          ) : (
            <ul>
              {traza.revisiones.map((r, i) => (
                <li key={i}>
                  {fecha(r.fecha)} · {ACCION[r.accion]}
                  {r.criterio_id && <> en «{r.criterio_id}»</>}
                  {r.valor_anterior && r.valor_nuevo && r.accion === "ajustar_nivel" && (
                    <>
                      : {r.valor_anterior} → {r.valor_nuevo}
                    </>
                  )}
                  {r.justificacion && <div className="secundario">{r.justificacion}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <button className="boton secundario" type="button" onClick={verTraza}>
          Ver traza
        </button>
      )}
    </>
  );
}

function TarjetaCriterio(props: {
  id: string;
  info: Criterio | null;
  datos: CriterioEvaluado | null;
  editable: boolean;
  alAjustar: (nivel: string, justificacion: string) => Promise<boolean>;
  alRetro: (cuerpo: { fortalezas: string[]; debilidades: string[]; recomendaciones: string[] }) => Promise<boolean>;
}) {
  const { id, info, datos, editable } = props;
  const [nuevo, setNuevo] = useState<string | null>(null);
  const [justificacion, setJustificacion] = useState("");
  const [retro, setRetro] = useState(false);
  const [fortalezas, setFortalezas] = useState("");
  const [debilidades, setDebilidades] = useState("");
  const [recomendaciones, setRecomendaciones] = useState("");

  const final = datos?.nivel_final ?? datos?.nivel_ia ?? null;
  const niveles = info ? [...info.niveles].sort((a, b) => a.valor - b.valor) : [];
  const nombre = (nid: string | null) => info?.niveles.find((n) => n.id === nid)?.nombre ?? nid ?? "—";

  async function ajustar(evento: FormEvent) {
    evento.preventDefault();
    if (nuevo && (await props.alAjustar(nuevo, justificacion.trim()))) {
      setNuevo(null);
      setJustificacion("");
    }
  }

  function abrirRetro() {
    setFortalezas((datos?.fortalezas ?? []).join("\n"));
    setDebilidades((datos?.debilidades ?? []).join("\n"));
    setRecomendaciones((datos?.recomendaciones ?? []).join("\n"));
    setRetro(true);
  }

  async function guardarRetro(evento: FormEvent) {
    evento.preventDefault();
    const ok = await props.alRetro({
      fortalezas: lineas(fortalezas),
      debilidades: lineas(debilidades),
      recomendaciones: lineas(recomendaciones),
    });
    if (ok) setRetro(false);
  }

  return (
    <article className="tarjeta">
      <h2 style={{ marginTop: 0 }}>
        {info?.nombre ?? id} {info && <span className="secundario">· {info.peso} %</span>}
      </h2>
      {!datos?.nivel_ia && <p className="aviso">La IA no propuso nivel en este criterio. Elige uno tú.</p>}

      {niveles.length > 0 ? (
        <div className="escalones" role="group" aria-label={`Nivel de ${info?.nombre ?? id}`}>
          {niveles.map((n, i) => {
            const esIa = n.id === datos?.nivel_ia;
            const elegido = n.id === final;
            return (
              <button
                key={n.id}
                type="button"
                className={`escalon${esIa ? " ia" : ""}${elegido ? " elegido" : ""}`}
                style={{ paddingTop: 8 + i * 10 }}
                aria-pressed={elegido}
                disabled={!editable || elegido}
                onClick={() => setNuevo(n.id)}
                title={n.descriptor}
              >
                {n.nombre}
                <span className="quien">
                  {esIa && "propuso la IA"}
                  {esIa && elegido && datos?.nivel_final && " · "}
                  {elegido && datos?.nivel_final && !esIa && "eligió el docente"}
                  {elegido && datos?.nivel_final && esIa && "confirmado"}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <p>
          Nivel: <strong>{nombre(final)}</strong>
          {datos?.nivel_ia && datos.nivel_final && datos.nivel_ia !== datos.nivel_final && (
            <span className="secundario"> (la IA propuso {nombre(datos.nivel_ia)})</span>
          )}
        </p>
      )}

      {nuevo && (
        <form onSubmit={ajustar} className="tarjeta" style={{ background: "var(--verde-claro-2)" }}>
          <p>
            Cambiar a <strong>{nombre(nuevo)}</strong>
          </p>
          <label className="campo">
            ¿Por qué? (obligatorio)
            <span className="ayuda">El estudiante verá esta justificación en lugar de la de la IA.</span>
            <textarea value={justificacion} onChange={(e) => setJustificacion(e.target.value)} maxLength={2000} required />
          </label>
          <div className="fila">
            <button className="boton" type="submit" disabled={!justificacion.trim()}>
              Guardar nivel
            </button>
            <button className="boton secundario" type="button" onClick={() => setNuevo(null)}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {datos?.justificacion && (
        <>
          <h3>Justificación de la IA</h3>
          <p>{datos.justificacion}</p>
        </>
      )}
      {datos?.evidencias.map((e, i) => (
        <blockquote className={`cita${e.encontrada === false ? " no" : ""}`} key={i}>
          «{e.fragmento}»
          <div className="donde">
            {e.encontrada === false ? "✗ No se encontró en la entrega" : e.encontrada ? "✓ Encontrada" : "Sin verificar"} · {e.archivo} ·{" "}
            {e.ubicacion}
          </div>
        </blockquote>
      ))}

      {retro ? (
        <form onSubmit={guardarRetro}>
          <p className="ayuda">Una idea por línea (máximo 10). El estudiante lo verá tal cual.</p>
          <label className="campo">
            Lo que hizo bien
            <textarea value={fortalezas} onChange={(e) => setFortalezas(e.target.value)} />
          </label>
          <label className="campo">
            Lo que falta
            <textarea value={debilidades} onChange={(e) => setDebilidades(e.target.value)} />
          </label>
          <label className="campo">
            Para mejorar
            <textarea value={recomendaciones} onChange={(e) => setRecomendaciones(e.target.value)} />
          </label>
          <div className="fila">
            <button className="boton" type="submit">
              Guardar retroalimentación
            </button>
            <button className="boton secundario" type="button" onClick={() => setRetro(false)}>
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <>
          <ListaRetro titulo="Lo que hizo bien" items={datos?.fortalezas ?? []} />
          <ListaRetro titulo="Lo que falta" items={datos?.debilidades ?? []} />
          <ListaRetro titulo="Para mejorar" items={datos?.recomendaciones ?? []} />
          {editable && datos && (
            <button className="boton secundario" type="button" onClick={abrirRetro}>
              Editar retroalimentación
            </button>
          )}
        </>
      )}
    </article>
  );
}

function ListaRetro({ titulo, items }: { titulo: string; items: string[] }) {
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
