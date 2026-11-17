import { useEffect, useState } from "react";
import { api } from "../api";

type ProyectoDatos = {
  titulo: string;
  abstract: string;
  tecnologias: string[];
  aportes: string[];
  equipo: { nombre: string; rol: string; foto_url: string | null }[];
};

export default function Proyecto() {
  const [datos, setDatos] = useState<ProyectoDatos | null>(null);

  useEffect(() => {
    api<ProyectoDatos>("/api/proyecto").then(setDatos);
  }, []);

  if (!datos) return <p>Cargando…</p>;
  return (
    <>
      <h1>{datos.titulo}</h1>
      <p>{datos.abstract}</p>
      <h2>Tecnologías</h2>
      <ul>
        {datos.tecnologias.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      <h2>Aportes</h2>
      <ul>
        {datos.aportes.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      <h2>Equipo</h2>
      <div className="equipo">
        {datos.equipo.map((p) => (
          <article className="tarjeta" key={p.nombre}>
            <div className="foto">{p.foto_url ? <img src={p.foto_url} alt="" /> : "[foto]"}</div>
            <h2>{p.nombre}</h2>
            <p className="secundario">{p.rol}</p>
          </article>
        ))}
      </div>
    </>
  );
}
