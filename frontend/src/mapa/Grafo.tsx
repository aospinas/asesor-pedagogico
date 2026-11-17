import { useEffect, useState } from "react";

type Nodo = {
  id: string;
  tipo: string;
  etiqueta: string;
  nivel: string | null;
  que_profundizar: string[];
  evidencias: { archivo: string; fragmento: string }[];
};
type Mapa = { nodos: Nodo[]; aristas: { origen: string; destino: string }[] };

const ALTURA: Record<string, number> = {
  "Por fortalecer": 80,
  Básico: 180,
  Medio: 280,
  Alto: 400,
};

export default function Grafo({ mapa }: { mapa: Mapa }) {
  const [elegido, setElegido] = useState<Nodo | null>(null);
  const [listo, setListo] = useState(false);

  useEffect(() => {
    let cancelado = false;
    let grafo: { destroy: () => void; png: (opciones: object) => string } | null = null;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (cancelado) return;
      const instancia = cytoscape({
        container: document.getElementById("mapa"),
        elements: [
          ...mapa.nodos.map((n) => ({
            data: { id: n.id, label: n.etiqueta, tipo: n.tipo, nivel: n.nivel || "" },
            position:
              n.tipo === "tema"
                ? { x: 80 + mapa.nodos.indexOf(n) * 40, y: 460 - (ALTURA[n.nivel || ""] || 200) }
                : undefined,
          })),
          ...mapa.aristas.map((a, i) => ({ data: { id: `a${i}`, source: a.origen, target: a.destino } })),
        ],
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "font-size": 12,
              "text-wrap": "wrap",
              "text-max-width": "90px",
              color: "#15241c",
              "background-color": "#dcebe3",
              "border-width": 1,
              "border-color": "#0b5d3b",
            },
          },
          { selector: 'node[nivel = "Alto"]', style: { "background-color": "#0b5d3b", color: "#ffffff" } },
          { selector: 'node[nivel = "Por fortalecer"]', style: { "border-color": "#b42318" } },
          { selector: "node:selected", style: { "border-width": 3, "border-color": "#00b4d8" } },
          { selector: "edge", style: { width: 1, "line-color": "#8da197", "curve-style": "bezier" } },
        ],
        layout: { name: "breadthfirst", directed: true, spacingFactor: 1.1 },
      });
      instancia.on("tap", "node", (evento) => {
        const id = evento.target.id();
        setElegido(mapa.nodos.find((n) => n.id === id) || null);
      });
      grafo = instancia;
      (window as unknown as { __mapa?: typeof instancia }).__mapa = instancia;
      setListo(true);
    })();
    return () => {
      cancelado = true;
      grafo?.destroy();
    };
  }, [mapa]);

  function descargarPng() {
    const guardado = (window as unknown as { __mapa?: { png: (o: object) => string } }).__mapa;
    if (!guardado) return;
    const enlace = document.createElement("a");
    enlace.href = guardado.png({ full: true, bg: "#ffffff", scale: 2 });
    enlace.download = "mapa.png";
    enlace.click();
  }

  function descargarJson() {
    const blob = new Blob([JSON.stringify(mapa, null, 2)], { type: "application/json" });
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(blob);
    enlace.download = "mapa.json";
    enlace.click();
  }

  return (
    <>
      <div id="mapa" role="img" aria-label="Mapa mental de temas de inteligencia artificial" />
      {!listo && <p>Dibujando el mapa…</p>}
      <div className="fila">
        <button className="boton secundario" onClick={descargarPng}>
          Descargar PNG
        </button>
        <button className="boton secundario" onClick={descargarJson}>
          Descargar JSON
        </button>
      </div>
      {elegido && (
        <article className="tarjeta">
          <h2>
            {elegido.etiqueta} {elegido.nivel ? `· ${elegido.nivel}` : ""}
          </h2>
          {elegido.que_profundizar.map((t) => (
            <p key={t}>{t}</p>
          ))}
          {elegido.evidencias.map((e, i) => (
            <blockquote className="cita si" key={i}>
              {e.archivo}: {e.fragmento}
            </blockquote>
          ))}
        </article>
      )}
    </>
  );
}
