// Mapa mental en bandas de altura (Cordillera): Alto arriba, Por fortalecer abajo.
// Cytoscape se carga solo aquí, con import() dinámico. Dibuja en canvas: las etiquetas
// son texto plano, nunca HTML.
import type { Core, ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MapaMental, NivelDominio, NodoMapa } from "../api";
import { Nivel } from "../componentes";
import { ALTURA, ICONO, descargar } from "../util";

const BANDAS: NivelDominio[] = ["Alto", "Medio", "Básico", "Por fortalecer"];
const ALTO_BANDA = 130;
const ANCHO = 1000;
const ARRIBA = 90; // fila de laboratorios
const ABAJO = ARRIBA + BANDAS.length * ALTO_BANDA + 70; // fila de categorías

function repartir(cuantos: number, i: number): number {
  return cuantos <= 1 ? ANCHO / 2 : 60 + (i * (ANCHO - 120)) / (cuantos - 1);
}

function elementos(mapa: MapaMental): ElementDefinition[] {
  const temas = mapa.nodos.filter((n) => n.tipo === "tema");
  const categorias = mapa.nodos.filter((n) => n.tipo === "categoria");
  const labs = mapa.nodos.filter((n) => n.tipo === "laboratorio");
  const porBanda = new Map<string, NodoMapa[]>();
  for (const t of temas) {
    const banda = t.nivel ?? "Por fortalecer";
    porBanda.set(banda, [...(porBanda.get(banda) ?? []), t]);
  }
  const fondo: ElementDefinition[] = BANDAS.map((b, i) => ({
    data: { id: `banda-${i}`, label: `${ICONO[b]} ${b} · ${ALTURA[b].toLocaleString("es-CO")} m`, banda: i % 2 },
    position: { x: ANCHO / 2, y: ARRIBA + 60 + i * ALTO_BANDA + ALTO_BANDA / 2 },
    classes: "banda",
    selectable: false,
    grabbable: false,
  }));
  const nodo = (n: NodoMapa, x: number, y: number): ElementDefinition => ({
    data: { id: n.id, label: n.etiqueta, tipo: n.tipo, nivel: n.nivel ?? "" },
    position: { x, y },
  });
  return [
    ...fondo,
    ...labs.map((n, i) => nodo(n, repartir(labs.length, i), ARRIBA)),
    ...categorias.map((n, i) => nodo(n, repartir(categorias.length, i), ABAJO)),
    ...BANDAS.flatMap((b, i) => {
      const lista = porBanda.get(b) ?? [];
      return lista.map((n, j) => nodo(n, repartir(lista.length, j), ARRIBA + 60 + i * ALTO_BANDA + ALTO_BANDA / 2));
    }),
    ...mapa.aristas.map((a, i) => ({ data: { id: `arista-${i}`, source: a.origen, target: a.destino } })),
  ];
}

export default function Grafo({ mapa, busqueda, nivel }: { mapa: MapaMental; busqueda: string; nivel: string }) {
  const lienzo = useRef<HTMLDivElement>(null);
  const grafo = useRef<Core | null>(null);
  const [elegido, setElegido] = useState<NodoMapa | null>(null);
  const [estado, setEstado] = useState<"cargando" | "listo" | "error">("cargando");
  const porId = useMemo(() => new Map(mapa.nodos.map((n) => [n.id, n])), [mapa]);

  useEffect(() => {
    let cancelado = false;
    import("cytoscape")
      .then(({ default: cytoscape }) => {
        if (cancelado || !lienzo.current) return;
        const quieto = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        const cy = cytoscape({
          container: lienzo.current,
          elements: elementos(mapa),
          layout: { name: "preset", fit: true, padding: 24, animate: !quieto, animationDuration: 300 },
          minZoom: 0.3,
          maxZoom: 2.5,
          style: [
            {
              selector: "node",
              style: {
                label: "data(label)",
                "font-family": "Source Sans 3, system-ui, sans-serif",
                "font-size": 13,
                "text-wrap": "wrap",
                "text-max-width": "110px",
                "text-valign": "center",
                color: "#15241c",
                "background-color": "#dcebe3",
                "border-width": 1,
                "border-color": "#0b5d3b",
                shape: "round-rectangle",
                width: 120,
                height: 44,
              },
            },
            { selector: 'node[tipo = "categoria"]', style: { "background-color": "#0b5d3b", color: "#ffffff", "font-weight": 700 } },
            { selector: 'node[tipo = "laboratorio"]', style: { "background-color": "#ffffff", "border-style": "dashed" } },
            { selector: 'node[nivel = "Alto"]', style: { "background-color": "#0b5d3b", color: "#ffffff" } },
            { selector: 'node[nivel = "Por fortalecer"]', style: { "background-color": "#fdf0ef", "border-color": "#b42318" } },
            {
              selector: "node.banda",
              style: {
                shape: "rectangle",
                width: ANCHO + 80,
                height: ALTO_BANDA,
                "background-color": "#f3f5f1",
                "background-opacity": 1,
                "border-width": 0,
                label: "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "font-size": 12,
                color: "#44564b",
                "z-compound-depth": "bottom",
                "z-index": 0,
                events: "no",
              },
            },
            { selector: 'node.banda[banda = 1]', style: { "background-color": "#e7eeea" } },
            { selector: "edge", style: { width: 1.5, "line-color": "#8da197", "curve-style": "bezier", "z-index": 1 } },
            { selector: ".ruta", style: { "line-color": "#00b4d8", width: 3, "z-index": 5 } },
            { selector: "node.ruta", style: { "border-color": "#00739a", "border-width": 3 } },
            { selector: ".coincide", style: { "border-color": "#00739a", "border-width": 4 } },
            { selector: ".oculto", style: { opacity: 0.12 } },
          ],
        });
        cy.on("tap", "node", (evento) => {
          const n = evento.target;
          cy.elements().removeClass("ruta");
          n.closedNeighborhood().addClass("ruta");
          setElegido(porId.get(n.id()) ?? null);
        });
        cy.on("tap", (evento) => {
          if (evento.target === cy) {
            cy.elements().removeClass("ruta");
            setElegido(null);
          }
        });
        grafo.current = cy;
        setEstado("listo");
      })
      .catch(() => !cancelado && setEstado("error"));
    return () => {
      cancelado = true;
      grafo.current?.destroy();
      grafo.current = null;
    };
  }, [mapa, porId]);

  // Búsqueda y filtro por nivel: se resaltan o se apagan nodos, no se borran.
  useEffect(() => {
    const cy = grafo.current;
    if (!cy || estado !== "listo") return;
    const texto = busqueda.trim().toLocaleLowerCase("es");
    cy.nodes().not(".banda").forEach((n) => {
      const dato = porId.get(n.id());
      n.toggleClass("coincide", texto !== "" && (dato?.etiqueta.toLocaleLowerCase("es").includes(texto) ?? false));
      n.toggleClass("oculto", nivel !== "" && dato?.tipo === "tema" && dato.nivel !== nivel);
    });
  }, [busqueda, nivel, estado, porId]);

  function png() {
    const cy = grafo.current;
    if (cy) descargar(cy.png({ full: true, bg: "#ffffff", scale: 2, output: "blob" }), "mapa-mental.png");
  }

  function json() {
    descargar(new Blob([JSON.stringify(mapa, null, 2)], { type: "application/json" }), "mapa-mental.json");
  }

  return (
    <div className="panel-mapa">
      <div>
        <div className="mapa-lienzo">
          <div ref={lienzo} className="cy" role="img" aria-label="Mapa mental: temas de IA ordenados por altura según tu nivel" />
        </div>
        {estado === "cargando" && <p className="secundario">Dibujando el mapa…</p>}
        {estado === "error" && <p className="error">No se pudo dibujar el mapa. Abajo está la misma información en lista.</p>}
        <div className="fila">
          <button className="boton secundario" type="button" onClick={png} disabled={estado !== "listo"}>
            Descargar PNG
          </button>
          <button className="boton secundario" type="button" onClick={json}>
            Descargar JSON
          </button>
        </div>
      </div>
      <aside className="tarjeta" aria-live="polite" style={{ margin: 0 }}>
        {elegido ? (
          <>
            <h2 style={{ marginTop: 0 }}>{elegido.etiqueta}</h2>
            <Nivel nivel={elegido.nivel} />
            {elegido.que_profundizar.length > 0 && (
              <>
                <h3 style={{ marginTop: 12 }}>Qué profundizar</h3>
                <ul>
                  {elegido.que_profundizar.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </>
            )}
            {elegido.evidencias.map((e, i) => (
              <blockquote className="cita" key={i}>
                «{e.fragmento}»
                <div className="donde">
                  {e.archivo} · {e.ubicacion}
                </div>
              </blockquote>
            ))}
          </>
        ) : (
          <p className="secundario">Toca un tema para ver tu nivel, la evidencia y qué profundizar.</p>
        )}
      </aside>
    </div>
  );
}
