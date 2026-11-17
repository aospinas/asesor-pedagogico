import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, enviarJson, type Cohorte, type Laboratorio } from "../api";
import { Estado } from "../componentes";

const mensaje = (e: unknown) => (e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");

export default function Laboratorios() {
  const [cohortes, setCohortes] = useState<Cohorte[] | null>(null);
  const [labs, setLabs] = useState<Laboratorio[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  function cargar() {
    Promise.all([api<Cohorte[]>("/api/cohortes"), api<Laboratorio[]>("/api/laboratorios")])
      .then(([c, l]) => {
        setCohortes(c);
        setLabs(l);
      })
      .catch((e) => setError(mensaje(e)));
  }
  useEffect(cargar, []);

  async function crearCohorte(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const forma = evento.currentTarget;
    const datos = new FormData(forma);
    setAviso("");
    try {
      await api("/api/cohortes", enviarJson({ nombre: datos.get("nombre"), periodo: datos.get("periodo") }));
      forma.reset();
      setAviso("Cohorte creada.");
      cargar();
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  async function crearLab(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const forma = evento.currentTarget;
    const datos = new FormData(forma);
    const temas = String(datos.get("temas") || "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    setAviso("");
    try {
      await api(
        "/api/laboratorios",
        enviarJson({
          cohorte_id: datos.get("cohorte_id"),
          titulo: datos.get("titulo"),
          descripcion: datos.get("descripcion"),
          objetivos: datos.get("objetivos"),
          temas_ia: temas,
        }),
      );
      forma.reset();
      setAviso("Laboratorio creado. Ábrelo para cargar su rúbrica.");
      cargar();
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  if (!cohortes) return <Estado cargando={!error} error={error} />;
  const nombreCohorte = (id: string) => cohortes.find((c) => c.id === id)?.nombre ?? "—";

  return (
    <>
      <h1>Laboratorios</h1>
      <p className="secundario">Crea la cohorte, luego el laboratorio, y después carga su rúbrica.</p>
      {aviso && (
        <p className="aviso" role="status">
          {aviso}
        </p>
      )}

      {labs.length > 0 && (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Laboratorio</th>
                <th>Cohorte</th>
                <th>Temas de IA</th>
              </tr>
            </thead>
            <tbody>
              {labs.map((l) => (
                <tr key={l.id}>
                  <td>
                    <Link to={`/laboratorios/${l.id}`}>{l.titulo}</Link>
                  </td>
                  <td>{nombreCohorte(l.cohorte_id)}</td>
                  <td>{l.temas_ia.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rejilla">
        <form className="tarjeta" onSubmit={crearCohorte}>
          <h2 style={{ marginTop: 0 }}>Nueva cohorte</h2>
          <label className="campo">
            Nombre
            <input name="nombre" maxLength={80} placeholder="Profundización I - IA" required />
          </label>
          <label className="campo">
            Periodo
            <input name="periodo" maxLength={40} placeholder="2026-2" required />
          </label>
          <button className="boton" type="submit">
            Crear cohorte
          </button>
        </form>

        <form className="tarjeta" onSubmit={crearLab}>
          <h2 style={{ marginTop: 0 }}>Nuevo laboratorio</h2>
          {cohortes.length === 0 ? (
            <p className="aviso">Primero crea una cohorte.</p>
          ) : (
            <>
              <label className="campo">
                Cohorte
                <select name="cohorte_id" required>
                  {cohortes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre} ({c.periodo})
                    </option>
                  ))}
                </select>
              </label>
              <label className="campo">
                Título
                <input name="titulo" maxLength={160} required />
              </label>
              <label className="campo">
                Descripción
                <textarea name="descripcion" maxLength={5000} required />
              </label>
              <label className="campo">
                Objetivos
                <textarea name="objetivos" maxLength={5000} required />
              </label>
              <label className="campo">
                Temas de IA
                <span className="ayuda">Separados por coma, como «Aprendizaje supervisado: regresión».</span>
                <input name="temas" />
              </label>
              <button className="boton" type="submit">
                Crear laboratorio
              </button>
            </>
          )}
        </form>
      </div>
    </>
  );
}
