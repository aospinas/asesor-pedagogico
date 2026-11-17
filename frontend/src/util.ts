// Utilidades sin pantalla (se prueban con Vitest en util.test.ts).
import type { EstadoEvaluacion, Motivo, NivelDominio } from "./api";

/** 3.4 → "3,4" (decimales como se escriben en Colombia). */
export function coma(valor: number | null | undefined, decimales = 1): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return valor.toFixed(decimales).replace(".", ",");
}

/** Altura de cada nivel en la metáfora de Cordillera (D-06): de Manizales al Nevado del Ruiz. */
export const ALTURA: Record<NivelDominio, number> = {
  "Por fortalecer": 2150,
  Básico: 3000,
  Medio: 4100,
  Alto: 5321,
};

/** Icono que acompaña siempre al color: nunca solo color (RNF-11). */
export const ICONO: Record<NivelDominio, string> = {
  Alto: "▲",
  Medio: "◆",
  Básico: "●",
  "Por fortalecer": "○",
};

/** Nivel de dominio a partir de una nota de 0 a 5 (SRS sección 9). */
export function nivelDe(nota: number): NivelDominio {
  const n = Math.round(nota * 10) / 10;
  if (n >= 4.5) return "Alto";
  if (n >= 3.5) return "Medio";
  if (n >= 3.0) return "Básico";
  return "Por fortalecer";
}

/** Una nota (0-5) llevada a metros: 0 → 2150 m (Manizales), 5 → 5321 m (el Nevado). */
export function metros(nota: number): number {
  return Math.round(2150 + (Math.max(0, Math.min(5, nota)) / 5) * (5321 - 2150));
}

export const ESTADO: Record<EstadoEvaluacion, string> = {
  en_proceso: "En proceso",
  en_revision: "En revisión",
  revision_manual: "Revisión manual",
  aprobada: "Aprobada",
  publicada: "Publicada",
};

export const MOTIVO: Record<Motivo, string> = {
  cita_no_encontrada: "Cita no encontrada",
  alerta_inyeccion: "Posible inyección de prompt",
  baja_coincidencia: "Baja coincidencia",
  sin_propuesta: "Sin propuesta de la IA",
};

export function fecha(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("es-CO", { day: "numeric", month: "short", year: "numeric" });
}

/** Puntos de un perfil de ascenso (SVG): x repartido a lo ancho, y según la nota (0-5). */
export function puntosPerfil(notas: number[], ancho: number, alto: number, margen = 24): [number, number][] {
  if (notas.length === 0) return [];
  const util = ancho - margen * 2;
  return notas.map((nota, i) => {
    const x = notas.length === 1 ? ancho / 2 : margen + (i * util) / (notas.length - 1);
    const y = alto - margen - (Math.max(0, Math.min(5, nota)) / 5) * (alto - margen * 2);
    return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
  });
}

/** Descarga un archivo hecho en el navegador (PNG o JSON del mapa). */
export function descargar(contenido: Blob | string, nombre: string): void {
  const enlace = document.createElement("a");
  enlace.href = typeof contenido === "string" ? contenido : URL.createObjectURL(contenido);
  enlace.download = nombre;
  enlace.click();
  if (typeof contenido !== "string") setTimeout(() => URL.revokeObjectURL(enlace.href), 1000);
}
