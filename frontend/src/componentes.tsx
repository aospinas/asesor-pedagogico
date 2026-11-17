// Piezas compartidas de Cordillera. Todo el texto se muestra como texto (React lo escapa):
// nunca se usa dangerouslySetInnerHTML.
import { useEffect, useRef, useState } from "react";
import type { NivelDominio } from "./api";
import { ICONO, coma, metros, puntosPerfil } from "./util";

const CLASE_NIVEL: Record<NivelDominio, string> = {
  Alto: "alto",
  Medio: "medio",
  Básico: "basico",
  "Por fortalecer": "fortalecer",
};

/** Nivel de dominio: icono + texto + color (nunca solo color). */
export function Nivel({ nivel }: { nivel: NivelDominio | null }) {
  if (!nivel) return null;
  return (
    <span className={`nivel ${CLASE_NIVEL[nivel]}`}>
      <span aria-hidden="true">{ICONO[nivel]}</span> {nivel}
    </span>
  );
}

/** Curvas de nivel del encabezado y del inicio, con el casquete glaciar en la cumbre. */
export function Curvas({ alto = 90 }: { alto?: number }) {
  return (
    <svg className="curvas" viewBox={`0 0 1200 ${alto}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={`M0 ${alto * 0.78} C 200 ${alto * 0.22}, 400 ${alto * 0.9}, 600 ${alto * 0.44} C 800 0, 1000 ${alto * 0.66}, 1200 ${alto * 0.22} V ${alto} H 0 Z`} fill="#084a2f" />
      <path d={`M0 ${alto * 0.87} C 220 ${alto * 0.44}, 480 ${alto * 0.98}, 700 ${alto * 0.55} C 900 ${alto * 0.22}, 1060 ${alto * 0.78}, 1200 ${alto * 0.4} V ${alto} H 0 Z`} fill="#063c26" />
      <path d={`M770 ${alto * 0.2} C 820 ${alto * 0.07}, 880 ${alto * 0.07}, 930 ${alto * 0.2} C 890 ${alto * 0.04}, 820 ${alto * 0.04}, 770 ${alto * 0.2} Z`} fill="#00b4d8" />
    </svg>
  );
}

/** Número que cuenta hasta su valor (máx. 400 ms; sin animación si el usuario la pide así). */
export function Cifra({ valor }: { valor: number | null }) {
  const [mostrado, setMostrado] = useState(valor);
  const anterior = useRef(valor);
  useEffect(() => {
    const desde = anterior.current ?? valor ?? 0;
    anterior.current = valor;
    if (valor === null) return setMostrado(null);
    const quieto = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (quieto || desde === valor) return setMostrado(valor);
    const inicio = performance.now();
    let cuadro = 0;
    const paso = (ahora: number) => {
      const t = Math.min(1, (ahora - inicio) / 400);
      setMostrado(desde + (valor - desde) * t);
      if (t < 1) cuadro = requestAnimationFrame(paso);
    };
    cuadro = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(cuadro);
  }, [valor]);
  return <>{coma(mostrado)}</>;
}

/** La nota como altímetro: cifra grande y un perfil que marca la preliminar y la final. */
export function Altimetro({ preliminar, final }: { preliminar: number | null; final: number | null }) {
  const nota = final ?? preliminar;
  const y = (n: number | null) => (n === null ? 60 : 62 - (n / 5) * 52);
  return (
    <div className="altimetro">
      <div>
        <div className="cifra" aria-label={`Nota ${nota === null ? "sin calcular" : coma(nota)} de 5`}>
          <Cifra valor={nota} />
        </div>
        <div className="de">
          de 5,0 {nota !== null && <>· {metros(nota).toLocaleString("es-CO")} m</>}
        </div>
      </div>
      <svg viewBox="0 0 140 70" role="img" aria-label={`Preliminar ${coma(preliminar)}, final ${coma(final)}`}>
        <path d="M0 68 L40 40 L70 50 L105 14 L140 68 Z" fill="#dcebe3" />
        <path d="M95 22 L105 14 L115 22 Z" fill="#00b4d8" />
        {preliminar !== null && <circle cx="40" cy={y(preliminar)} r="5" fill="none" stroke="#0b5d3b" strokeDasharray="2 2" strokeWidth="2" />}
        {final !== null && <circle cx="105" cy={y(final)} r="6" fill="#00b4d8" />}
      </svg>
    </div>
  );
}

/** Perfil de ascenso: evolución entre laboratorios (área + línea) con la nota en cada cima. */
export function Perfil({ puntos, etiquetas }: { puntos: number[]; etiquetas: string[] }) {
  const ancho = 720;
  const alto = 220;
  const xy = puntosPerfil(puntos, ancho, alto, 34);
  if (xy.length === 0) return null;
  const linea = xy.map(([x, y]) => `${x},${y}`).join(" ");
  const area = `${xy[0][0]},${alto - 34} ${linea} ${xy[xy.length - 1][0]},${alto - 34}`;
  const descripcion = puntos.map((n, i) => `${etiquetas[i]}: ${coma(n)}`).join("; ");
  return (
    <svg className="grafica" viewBox={`0 0 ${ancho} ${alto}`} role="img" aria-label={`Perfil de ascenso. ${descripcion}`}>
      {[0, 2.5, 5].map((n) => {
        const yy = alto - 34 - (n / 5) * (alto - 68);
        return (
          <g key={n}>
            <line x1="34" x2={ancho - 34} y1={yy} y2={yy} stroke="#e7eeea" />
            <text x="6" y={yy + 4} fontSize="12" fill="#44564b">
              {coma(n)}
            </text>
          </g>
        );
      })}
      <polygon points={area} fill="#dcebe3" />
      <polyline points={linea} fill="none" stroke="#00b4d8" strokeWidth="3" strokeLinejoin="round" />
      {xy.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="5" fill="#0b5d3b" />
          <text x={x} y={y - 10} fontSize="13" fontWeight="700" textAnchor="middle" fill="#15241c">
            {coma(puntos[i])}
          </text>
          <text x={x} y={alto - 12} fontSize="12" textAnchor="middle" fill="#44564b">
            {etiquetas[i].length > 18 ? `${etiquetas[i].slice(0, 17)}…` : etiquetas[i]}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Barras horizontales de dominio (temas, competencias o cohortes). */
export function Barras({ filas }: { filas: { nombre: string; promedio: number; nivel: NivelDominio }[] }) {
  return (
    <div className="barras" role="list">
      {filas.map((f) => (
        <div className="barra-dominio" role="listitem" key={f.nombre}>
          <span>{f.nombre}</span>
          <div className="pista" aria-hidden="true">
            <div className="relleno" style={{ width: `${(f.promedio / 5) * 100}%` }} />
          </div>
          <span>
            {coma(f.promedio)} <Nivel nivel={f.nivel} />
          </span>
        </div>
      ))}
    </div>
  );
}

/** Estado de carga y error, igual en todas las pantallas. */
export function Estado({ cargando, error }: { cargando?: boolean; error?: string }) {
  if (error) return <p className="error" role="alert">{error}</p>;
  if (cargando) return <p className="secundario">Cargando…</p>;
  return null;
}
