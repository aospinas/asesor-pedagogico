import { type FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { ErrorApi, api, enviarJson, type Sesion } from "../api";
import { Curvas } from "../componentes";

const DESTINO = { estudiante: "/entregas", docente: "/tablero", administrador: "/admin" } as const;

export default function Inicio({ sesion, alEntrar }: { sesion: Sesion | null; alEntrar: (s: Sesion) => void }) {
  const [correo, setCorreo] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  if (sesion) {
    return <Navigate to={sesion.debe_cambiar_contrasena ? "/clave" : DESTINO[sesion.usuario.rol]} replace />;
  }

  async function entrar(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    setEnviando(true);
    try {
      alEntrar(await api<Sesion>("/api/sesion", enviarJson({ correo, contrasena })));
    } catch (e) {
      setError(e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");
    } finally {
      setContrasena("");
      setEnviando(false);
    }
  }

  return (
    <section className="inicio">
      <Curvas alto={600} />
      <form className="formulario" onSubmit={entrar}>
        <h1>Entrar</h1>
        <p className="lema">Sube tus laboratorios y mira cómo vas subiendo, criterio por criterio.</p>
        <label className="campo">
          Correo
          <input type="email" autoComplete="username" value={correo} onChange={(e) => setCorreo(e.target.value)} required />
        </label>
        <label className="campo">
          Contraseña
          <input
            type="password"
            autoComplete="current-password"
            value={contrasena}
            onChange={(e) => setContrasena(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="boton" type="submit" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>
        <p className="ayuda">¿Olvidaste tu contraseña? Pídele una temporal al administrador.</p>
      </form>
    </section>
  );
}
