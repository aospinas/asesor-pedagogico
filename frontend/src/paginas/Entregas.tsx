import { type FormEvent, useEffect, useRef, useState } from "react";
import { ErrorApi, api, type Entrega, type Laboratorio, type RubricaPublica } from "../api";
import { Estado } from "../componentes";
import { fecha } from "../util";

const TIPO = { pdf: "Informe", codigo: "Código", imagen: "Imagen", diapositivas: "Diapositivas", video: "Video" };

function Rubrica({ laboratorioId }: { laboratorioId: string }) {
  const [rubrica, setRubrica] = useState<RubricaPublica | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setRubrica(null);
    setError("");
    api<RubricaPublica>(`/api/laboratorios/${laboratorioId}/rubrica`)
      .then(setRubrica)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la rúbrica."));
  }, [laboratorioId]);
  if (error) return <p className="aviso">{error}</p>;
  if (!rubrica) return null;
  return (
    <details className="tarjeta">
      <summary>
        Rúbrica con la que te evalúan (versión {rubrica.numero}, {rubrica.estructura.criterios.length} criterios)
      </summary>
      {rubrica.estructura.criterios.map((c) => (
        <div key={c.id} style={{ marginTop: 12 }}>
          <h3>
            {c.nombre} <span className="secundario">· {c.peso} %</span>
          </h3>
          <ul>
            {c.niveles.map((n) => (
              <li key={n.id}>
                <strong>{n.nombre}:</strong> {n.descriptor}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </details>
  );
}

export default function Entregas() {
  const [laboratorios, setLaboratorios] = useState<Laboratorio[]>([]);
  const [entregas, setEntregas] = useState<Entrega[]>([]);
  const [elegido, setElegido] = useState("");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [mensaje, setMensaje] = useState("");
  const formulario = useRef<HTMLFormElement>(null);

  function cargar() {
    Promise.all([api<Laboratorio[]>("/api/laboratorios"), api<Entrega[]>("/api/mis-entregas")])
      .then(([labs, mias]) => {
        setLaboratorios(labs);
        setEntregas(mias);
        setElegido((e) => e || labs[0]?.id || "");
      })
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la página."))
      .finally(() => setCargando(false));
  }
  useEffect(cargar, []);

  const titulo = (id: string) => laboratorios.find((l) => l.id === id)?.titulo ?? "Laboratorio";

  async function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    setMensaje("");
    setError("");
    const datos = new FormData(evento.currentTarget);
    // Los campos vacíos no se mandan: el backend los toma como "no hay".
    for (const campo of ["codigo", "diapositivas"]) {
      const archivo = datos.get(campo);
      if (archivo instanceof File && archivo.size === 0) datos.delete(campo);
    }
    const imagenes = datos.getAll("imagenes").filter((a) => a instanceof File && a.size > 0);
    datos.delete("imagenes");
    imagenes.forEach((a) => datos.append("imagenes", a));
    if (!String(datos.get("enlace_github") || "").trim()) datos.delete("enlace_github");
    setEnviando(true);
    try {
      await api<Entrega>("/api/entregas", { method: "POST", body: datos });
      setMensaje("Listo, tu entrega quedó guardada. El docente la evalúa y te avisa cuando la publique.");
      formulario.current?.reset();
      cargar();
    } catch (e) {
      setError(e instanceof ErrorApi ? e.message : "No se pudo subir. Revisa tu internet.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <h1>Mis entregas</h1>
      <Estado cargando={cargando} />
      {!cargando && laboratorios.length === 0 && <p className="aviso">Todavía no hay laboratorios abiertos.</p>}

      {laboratorios.length > 0 && (
        <form ref={formulario} className="tarjeta" onSubmit={enviar}>
          <h2 style={{ marginTop: 0 }}>Nueva entrega</h2>
          <label className="campo">
            Laboratorio
            <select name="laboratorio_id" value={elegido} onChange={(e) => setElegido(e.target.value)} required>
              {laboratorios.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.titulo}
                </option>
              ))}
            </select>
          </label>
          {elegido && <Rubrica laboratorioId={elegido} />}
          <label className="campo">
            Informe en PDF (obligatorio)
            <span className="ayuda">Debe tener texto, no solo fotos de páginas.</span>
            <input type="file" name="informe" accept="application/pdf,.pdf" required />
          </label>
          <label className="campo">
            Código en ZIP
            <input type="file" name="codigo" accept=".zip,application/zip" />
          </label>
          <label className="campo">
            Enlace del repositorio en GitHub
            <input type="url" name="enlace_github" placeholder="https://github.com/usuario/repositorio" maxLength={200} />
          </label>
          <label className="campo">
            Imágenes (hasta 5)
            <input type="file" name="imagenes" accept="image/png,image/jpeg" multiple />
          </label>
          <label className="campo">
            Diapositivas (PPTX o PDF)
            <input type="file" name="diapositivas" accept=".pptx,.pdf" />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {mensaje && (
            <p className="exito" role="status">
              {mensaje}
            </p>
          )}
          <button className="boton" type="submit" disabled={enviando}>
            {enviando ? "Subiendo…" : "Subir entrega"}
          </button>
        </form>
      )}

      <h2>Lo que ya subiste</h2>
      {!cargando && entregas.length === 0 && <p className="secundario">Aún no has subido nada.</p>}
      {entregas.length > 0 && (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Laboratorio</th>
                <th>Fecha</th>
                <th>Archivos</th>
                <th>Rúbrica</th>
              </tr>
            </thead>
            <tbody>
              {entregas.map((e) => (
                <tr key={e.id}>
                  <td>{titulo(e.laboratorio_id)}</td>
                  <td>{fecha(e.fecha)}</td>
                  <td>
                    {e.evidencias.map((a) => (
                      <div key={a.id}>
                        <span className="etiqueta">{TIPO[a.tipo]}</span> {a.nombre}
                      </div>
                    ))}
                    {e.enlace_github && <div className="secundario">{e.enlace_github}</div>}
                  </td>
                  <td>{e.rubrica_version_numero ? `Versión ${e.rubrica_version_numero}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="ayuda">Cuando el docente publique tu evaluación, la verás en «Mi informe».</p>
    </>
  );
}
