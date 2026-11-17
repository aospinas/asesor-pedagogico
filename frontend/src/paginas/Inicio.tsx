import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Sesion } from "../api";

export default function Inicio({
  sesion,
  alEntrar,
}: {
  sesion: Sesion | null;
  alEntrar: (s: Sesion) => void;
}) {
  const [correo, setCorreo] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState("");
  const navegar = useNavigate();

  async function entrar(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    try {
      const nueva = await api<Sesion>("/api/sesion", {
        method: "POST",
        body: JSON.stringify({ correo, contrasena }),
      });
      alEntrar(nueva);
      navegar(nueva.usuario.rol === "docente" ? "/bandeja" : "/informe");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo entrar.");
    }
  }

  if (sesion) {
    return (
      <>
        <h1>Hola, {sesion.usuario.nombre}</h1>
        <p className="secundario">Ya estás en la plataforma. Usa el menú de arriba.</p>
      </>
    );
  }

  return (
    <>
      <h1>Entra a tu cuenta</h1>
      <p className="secundario">La IA propone. El sistema calcula la nota. El docente aprueba.</p>
      <form className="tarjeta" onSubmit={entrar}>
        {error && <p className="error">{error}</p>}
        <label className="campo">
          Correo
          <input type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} required />
        </label>
        <label className="campo">
          Contraseña
          <input
            type="password"
            value={contrasena}
            onChange={(e) => setContrasena(e.target.value)}
            required
          />
        </label>
        <button className="boton" type="submit">
          Entrar
        </button>
      </form>
    </>
  );
}
