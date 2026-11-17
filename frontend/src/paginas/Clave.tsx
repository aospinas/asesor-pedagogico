import { type FormEvent, useState } from "react";
import { ErrorApi, api, enviarJson, type Sesion } from "../api";

export default function Clave({ sesion, alCambiar }: { sesion: Sesion; alCambiar: (s: Sesion) => void }) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [error, setError] = useState("");
  const [listo, setListo] = useState(false);

  async function cambiar(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    setListo(false);
    if (nueva !== repetida) return setError("Las dos contraseñas nuevas no son iguales.");
    try {
      await api("/api/yo/contrasena", enviarJson({ actual, nueva }, "PUT"));
      setListo(true);
      alCambiar({ ...sesion, debe_cambiar_contrasena: false });
    } catch (e) {
      setError(e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");
    } finally {
      setActual("");
      setNueva("");
      setRepetida("");
    }
  }

  return (
    <section className="tarjeta" style={{ maxWidth: 480 }}>
      <h1>Cambiar contraseña</h1>
      {sesion.debe_cambiar_contrasena && (
        <p className="aviso">Tienes una contraseña temporal. Cámbiala para seguir.</p>
      )}
      <form onSubmit={cambiar}>
        <label className="campo">
          Contraseña actual
          <input type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} required />
        </label>
        <label className="campo">
          Contraseña nueva
          <span className="ayuda">Mínimo 10 caracteres.</span>
          <input
            type="password"
            autoComplete="new-password"
            minLength={10}
            value={nueva}
            onChange={(e) => setNueva(e.target.value)}
            required
          />
        </label>
        <label className="campo">
          Repite la contraseña nueva
          <input
            type="password"
            autoComplete="new-password"
            minLength={10}
            value={repetida}
            onChange={(e) => setRepetida(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {listo && (
          <p className="exito" role="status">
            Listo, tu contraseña quedó cambiada.
          </p>
        )}
        <button className="boton" type="submit">
          Guardar
        </button>
      </form>
    </section>
  );
}
