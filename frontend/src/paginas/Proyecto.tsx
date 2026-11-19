// Página pública del proyecto y del equipo (RF-18, D-26). No necesita sesión.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, type Proyecto as TipoProyecto } from "../api";
import { Estado } from "../componentes";

const iniciales = (nombre: string) =>
  nombre
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase();

export default function Proyecto() {
  const [datos, setDatos] = useState<TipoProyecto | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TipoProyecto>("/api/proyecto")
      .then(setDatos)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la página."));
  }, []);

  if (!datos) return <Estado cargando={!error} error={error} />;

  return (
    <>
      <h1>{datos.nombre}</h1>
      <p className="secundario">Proyecto final · Profundización I — Inteligencia Artificial · Universidad de Manizales</p>
      <p className="tarjeta" style={{ fontFamily: "var(--titulo)", fontWeight: 700, fontSize: "1.2rem", color: "var(--verde)" }}>
        {datos.regla}
      </p>

      <h2>De qué se trata</h2>
      <p>{datos.abstract}</p>

      <h2>Qué aporta</h2>
      <ul>
        {datos.aportes.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>

      <h2>Tecnologías</h2>
      <div className="tabla-scroll">
        <table>
          <thead>
            <tr>
              <th>Tecnología</th>
              <th>Para qué</th>
            </tr>
          </thead>
          <tbody>
            {datos.tecnologias.map((t) => (
              <tr key={t.nombre}>
                <td>{t.nombre}</td>
                <td>{t.para_que}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 id="equipo">Equipo</h2>
      <div className="rejilla">
        {datos.equipo.map((m) => (
          <article className="tarjeta miembro" key={m.nombre} style={{ margin: 0 }}>
            {m.foto_url ? (
              <img src={m.foto_url} alt={`Foto de ${m.nombre}`} className="foto" />
            ) : (
              <div className="foto" aria-hidden="true">
                {iniciales(m.nombre)}
              </div>
            )}
            <div>
              <h3>{m.nombre}</h3>
              <p className="secundario" style={{ margin: "0 0 6px" }}>
                {m.rol}
              </p>
              <p style={{ margin: 0 }}>{m.aporte}</p>
            </div>
          </article>
        ))}
      </div>

      <div className="fila">
        <Link className="boton secundario" to="/bitacora">
          Ver la bitácora de uso de IA
        </Link>
        <a className="boton secundario" href={datos.repositorio} target="_blank" rel="noreferrer noopener">
          Código en GitHub
        </a>
      </div>
    </>
  );
}
