import { useEffect, useState } from "react";
import { api } from "../api";

export default function Bitacora() {
  const [texto, setTexto] = useState("");

  useEffect(() => {
    api<{ contenido: string }>("/api/bitacora").then((d) => setTexto(d.contenido));
  }, []);

  return (
    <>
      <h1>Bitácora de la IA</h1>
      <p className="secundario">Qué herramientas se usaron para construir esta plataforma y qué se decidió.</p>
      <article className="tarjeta bitacora">{texto || "Cargando…"}</article>
    </>
  );
}
