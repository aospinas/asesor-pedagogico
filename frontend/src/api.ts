// Cliente de la API y tipos (copiados de app/esquemas.py; los nombres son los mismos).
// La sesión va en una cookie segura que pone el backend: el frontend nunca guarda tokens.

export type Rol = "estudiante" | "docente" | "administrador";
export type NivelDominio = "Alto" | "Medio" | "Básico" | "Por fortalecer";
export type EstadoEvaluacion = "en_proceso" | "en_revision" | "revision_manual" | "aprobada" | "publicada";

export type Usuario = { id: string; nombre: string; correo: string; rol: Rol; activo: boolean; foto_url: string | null };
export type Sesion = { usuario: Usuario; debe_cambiar_contrasena: boolean };

export type Laboratorio = {
  id: string;
  cohorte_id: string;
  titulo: string;
  descripcion: string;
  objetivos: string;
  temas_ia: string[];
};

export type EvidenciaArchivo = {
  id: string;
  tipo: "pdf" | "codigo" | "imagen" | "diapositivas" | "video";
  nombre: string;
  sha256: string;
  tamano_bytes: number | null;
  resumen: string | null;
};
export type Entrega = {
  id: string;
  estudiante_id: string;
  laboratorio_id: string;
  rubrica_version_id: string;
  enlace_github: string | null;
  evidencias: EvidenciaArchivo[];
  fecha: string;
  rubrica_version_numero: number | null;
};

export type Nivel = { id: string; nombre: string; descriptor: string; valor: number };
export type Criterio = { id: string; nombre: string; competencia: string; peso: number; niveles: Nivel[] };
export type RubricaEstructura = { laboratorio: string; criterios: Criterio[] };
export type RubricaPublica = { numero: number; estructura: RubricaEstructura; fecha: string };
export type RubricaVersion = { id: string; numero: number; estructura: RubricaEstructura };

export type Cita = { archivo: string; ubicacion: string; fragmento: string };
export type CitaVerificada = Cita & { encontrada: boolean | null };

export type CriterioPublicado = {
  criterio_id: string;
  nivel_id: string;
  justificacion: string;
  evidencias: Cita[];
  fortalezas: string[];
  debilidades: string[];
  recomendaciones: string[];
};
export type EvaluacionPublicada = {
  id: string;
  entrega_id: string;
  laboratorio_id: string;
  nota_final: number;
  criterios: CriterioPublicado[];
  fecha_publicacion: string;
};

export type CriterioEvaluado = {
  criterio_id: string;
  nivel_ia: string | null;
  nivel_final: string | null;
  justificacion: string;
  evidencias: CitaVerificada[];
  fortalezas: string[];
  debilidades: string[];
  recomendaciones: string[];
};
export type Verificacion = {
  tipo: "sintaxis" | "estatico" | "pruebas";
  comando: string;
  codigo_salida: number | null;
  salida: string;
  duracion_ms: number;
  tiempo_agotado: boolean;
};
export type Motivo = "cita_no_encontrada" | "alerta_inyeccion" | "baja_coincidencia" | "sin_propuesta";
export type Evaluacion = {
  id: string;
  entrega_id: string;
  rubrica_version_id: string;
  estado: EstadoEvaluacion;
  proveedor: string;
  modelo: string;
  version_prompt: string;
  criterios: CriterioEvaluado[];
  verificaciones: Verificacion[];
  nota_preliminar: number | null;
  nota_final: number | null;
  tokens_entrada: number;
  tokens_salida: number;
  costo_usd: number;
  alerta_inyeccion: boolean;
  fecha: string;
  motivos: Motivo[];
  aviso: string | null;
};
export type EvaluacionResumen = {
  id: string;
  entrega_id: string;
  laboratorio_id: string;
  estudiante_id: string;
  estado: EstadoEvaluacion;
  nota_preliminar: number | null;
  motivos: Motivo[];
  fecha: string;
};
export type Revision = {
  accion: "ajustar_nivel" | "editar_retroalimentacion" | "aprobar" | "publicar";
  criterio_id: string | null;
  valor_anterior: string | null;
  valor_nuevo: string | null;
  justificacion: string | null;
  fecha: string;
};
export type Traza = {
  modelo: string;
  proveedor: string;
  version_prompt: string;
  evidencias: EvidenciaArchivo[];
  tokens_entrada: number;
  tokens_salida: number;
  fecha: string;
  fecha_aprobacion: string | null;
  fecha_publicacion: string | null;
  revisiones: Revision[];
};

export type ResultadoLaboratorio = {
  laboratorio_id: string;
  evaluacion_id: string;
  titulo: string;
  cohorte: string;
  nota_final: number;
  nivel: NivelDominio;
  fecha_publicacion: string;
};
export type Dominio = { promedio: number; nivel: NivelDominio; laboratorios: string[] };
export type Informe = {
  estudiante_id: string;
  nombre_estudiante: string;
  laboratorios: ResultadoLaboratorio[];
  promedio_general: number | null;
  cohortes: (Dominio & { cohorte: string })[];
  competencias: (Dominio & { competencia: string })[];
  temas: (Dominio & { categoria: string; tema: string })[];
  brechas: string[];
  plan: { resumen: string; acciones: { tema: string; que_hacer: string; recursos: string[] }[] } | null;
  generado: string;
};

export type NodoMapa = {
  id: string;
  tipo: "categoria" | "tema" | "laboratorio";
  etiqueta: string;
  nivel: NivelDominio | null;
  evidencias: Cita[];
  que_profundizar: string[];
};
export type MapaMental = { estudiante_id: string; nodos: NodoMapa[]; aristas: { origen: string; destino: string }[] };

export class ErrorApi extends Error {
  estado: number;
  constructor(estado: number, mensaje: string) {
    super(mensaje);
    this.estado = estado;
  }
}

/** Pide algo a la API. Los mensajes de error son los del backend (en español). */
export async function api<T>(camino: string, opciones: RequestInit = {}): Promise<T> {
  const headers = new Headers(opciones.headers);
  if (opciones.body && !(opciones.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const respuesta = await fetch(camino, { ...opciones, headers, credentials: "same-origin" });
  if (respuesta.status === 204) return undefined as T;
  const tipo = respuesta.headers.get("content-type") || "";
  if (!respuesta.ok) {
    let mensaje = "No se pudo completar la acción. Intenta de nuevo.";
    if (tipo.includes("json")) {
      const cuerpo = await respuesta.json().catch(() => null);
      if (cuerpo && typeof cuerpo.detail === "string") mensaje = cuerpo.detail;
    }
    throw new ErrorApi(respuesta.status, mensaje);
  }
  return (tipo.includes("json") ? respuesta.json() : respuesta.blob()) as Promise<T>;
}

export const enviarJson = (cuerpo: unknown, metodo = "POST"): RequestInit => ({
  method: metodo,
  body: JSON.stringify(cuerpo),
});
