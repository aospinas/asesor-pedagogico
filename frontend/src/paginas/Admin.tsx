import { type FormEvent, useEffect, useState } from "react";
import { ErrorApi, api, enviarJson, type Rol, type Usuario } from "../api";
import { Estado } from "../componentes";

const ROL: Record<Rol, string> = { estudiante: "Estudiante", docente: "Docente", administrador: "Administrador" };
const mensaje = (e: unknown) => (e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");

export default function Admin({ yo }: { yo: string }) {
  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [clave, setClave] = useState<{ id: string; nombre: string } | null>(null);

  function cargar() {
    api<Usuario[]>("/api/usuarios")
      .then(setUsuarios)
      .catch((e) => setError(mensaje(e)));
  }
  useEffect(cargar, []);

  async function crear(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const forma = evento.currentTarget;
    const d = new FormData(forma);
    setAviso("");
    try {
      await api(
        "/api/usuarios",
        enviarJson({ nombre: d.get("nombre"), correo: d.get("correo"), contrasena: d.get("contrasena"), rol: d.get("rol") }),
      );
      forma.reset();
      setAviso("Usuario creado. Entrégale su clave temporal: al entrar se le pide cambiarla.");
      cargar();
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  async function editar(u: Usuario, cambio: Partial<Pick<Usuario, "rol" | "activo">>) {
    setAviso("");
    try {
      await api(`/api/usuarios/${u.id}`, enviarJson(cambio, "PATCH"));
      cargar();
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  async function ponerClave(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    if (!clave) return;
    const d = new FormData(evento.currentTarget);
    setAviso("");
    try {
      await api(`/api/usuarios/${clave.id}/clave-temporal`, enviarJson({ contrasena: d.get("contrasena") }));
      setAviso(`Listo: ${clave.nombre} tiene clave temporal y debe cambiarla al entrar.`);
      setClave(null);
    } catch (e) {
      setAviso(mensaje(e));
    }
  }

  if (!usuarios) return <Estado cargando={!error} error={error} />;

  return (
    <>
      <h1>Usuarios</h1>
      {aviso && (
        <p className="aviso" role="status">
          {aviso}
        </p>
      )}

      <form className="tarjeta" onSubmit={crear}>
        <h2 style={{ marginTop: 0 }}>Nuevo usuario</h2>
        <div className="rejilla">
          <label className="campo">
            Nombre
            <input name="nombre" maxLength={120} required />
          </label>
          <label className="campo">
            Correo
            <input name="correo" type="email" required />
          </label>
          <label className="campo">
            Clave temporal
            <span className="ayuda">Mínimo 10 caracteres; la persona la cambia al entrar.</span>
            <input name="contrasena" type="password" autoComplete="new-password" minLength={10} required />
          </label>
          <label className="campo">
            Rol
            <select name="rol" defaultValue="estudiante">
              <option value="estudiante">Estudiante</option>
              <option value="docente">Docente</option>
              <option value="administrador">Administrador</option>
            </select>
          </label>
        </div>
        <button className="boton" type="submit">
          Crear usuario
        </button>
      </form>

      {clave && (
        <form className="tarjeta" onSubmit={ponerClave}>
          <h2 style={{ marginTop: 0 }}>Clave temporal para {clave.nombre}</h2>
          <label className="campo">
            Clave temporal nueva
            <input name="contrasena" type="password" autoComplete="new-password" minLength={10} required />
          </label>
          <div className="fila">
            <button className="boton" type="submit">
              Guardar
            </button>
            <button className="boton secundario" type="button" onClick={() => setClave(null)}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      <div className="tabla-scroll">
        <table>
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Correo</th>
              <th>Rol</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {usuarios.map((u) => (
              <tr key={u.id}>
                <td>{u.nombre}</td>
                <td>{u.correo}</td>
                <td>
                  {u.id === yo ? (
                    ROL[u.rol]
                  ) : (
                    <select
                      aria-label={`Rol de ${u.nombre}`}
                      value={u.rol}
                      onChange={(e) => editar(u, { rol: e.target.value as Rol })}
                    >
                      {Object.entries(ROL).map(([v, t]) => (
                        <option key={v} value={v}>
                          {t}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
                <td>{u.activo ? "Activo" : <span className="etiqueta rojo">Desactivado</span>}</td>
                <td>
                  {u.id !== yo && (
                    <div className="fila" style={{ margin: 0 }}>
                      <button className="boton secundario" type="button" onClick={() => editar(u, { activo: !u.activo })}>
                        {u.activo ? "Desactivar" : "Activar"}
                      </button>
                      <button className="boton secundario" type="button" onClick={() => setClave({ id: u.id, nombre: u.nombre })}>
                        Clave temporal
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
