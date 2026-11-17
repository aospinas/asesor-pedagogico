export type Usuario = {
  id: string;
  nombre: string;
  correo: string;
  rol: "estudiante" | "docente" | "administrador";
};

export type Sesion = { usuario: Usuario; debe_cambiar_contrasena: boolean };

export class ErrorApi extends Error {
  estado: number;
  constructor(estado: number, mensaje: string) {
    super(mensaje);
    this.estado = estado;
  }
}

export async function api<T>(camino: string, opciones: RequestInit = {}): Promise<T> {
  const headers = new Headers(opciones.headers);
  if (opciones.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const respuesta = await fetch(camino, { ...opciones, headers, credentials: "include" });
  if (respuesta.status === 204) return undefined as T;
  const tipo = respuesta.headers.get("content-type") || "";
  if (!respuesta.ok) {
    let mensaje = "No se pudo completar la acción.";
    if (tipo.includes("json")) {
      const cuerpo = await respuesta.json();
      if (typeof cuerpo.detail === "string") mensaje = cuerpo.detail;
    }
    throw new ErrorApi(respuesta.status, mensaje);
  }
  if (!tipo.includes("json")) return (await respuesta.blob()) as T;
  return respuesta.json();
}
