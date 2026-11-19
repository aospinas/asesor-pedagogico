// Tablero del estudiante (D-25). Solo trae lo publicado: de lo demás solo dice que está esperando.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, type MiTablero as TipoMiTablero } from "../api";
import { Barras, Cifra, Estado, Nivel } from "../componentes";
import { coma, fecha, metros } from "../util";

export default function MiTablero({ nombre }: { nombre: string }) {
  const [datos, setDatos] = useState<TipoMiTablero | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TipoMiTablero>("/api/mi-tablero")
      .then(setDatos)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar tu tablero."));
  }, []);

  if (!datos) return <Estado cargando={!error} error={error} />;
  const { ultima } = datos;
  const primerNombre = nombre.split(" ")[0];

  return (
    <>
      <h1>Hola, {primerNombre}</h1>
      <p className="secundario">Así va tu ascenso en el curso. Solo cuentan las evaluaciones que el docente ya publicó.</p>

      <div className="rejilla">
        <section className="tarjeta" style={{ margin: 0 }}>
          <div className="secundario">Tu promedio</div>
          {datos.promedio === null ? (
            <p>Aparece cuando el docente publique tu primera evaluación.</p>
          ) : (
            <>
              <div className="altimetro">
                <span className="cifra">
                  <Cifra valor={datos.promedio} />
                </span>
                <span className="de">de 5,0</span>
              </div>
              <Nivel nivel={datos.nivel} />
            </>
          )}
          <Cerro promedio={datos.promedio} />
        </section>

        <section className="tarjeta" style={{ margin: 0 }}>
          <div className="secundario">Tu última nota</div>
          {ultima ? (
            <>
              <h2 style={{ margin: "4px 0 8px" }}>{ultima.titulo}</h2>
              <div className="numero">{coma(ultima.nota)}</div>
              <p>
                <Nivel nivel={ultima.nivel} />{" "}
                {ultima.cambio !== null && ultima.cambio !== 0 && (
                  <span className={ultima.cambio > 0 ? "etiqueta" : "etiqueta alerta"}>
                    {ultima.cambio > 0 ? "▲ Subiste" : "▼ Bajaste"} {coma(Math.abs(ultima.cambio))}
                  </span>
                )}
              </p>
              <p className="secundario">Publicada el {fecha(ultima.fecha)}</p>
              <Link to={`/publicada/${ultima.evaluacion_id}`}>Ver la retroalimentación</Link>
            </>
          ) : (
            <p className="secundario">Todavía no tienes notas publicadas.</p>
          )}
        </section>
      </div>

      <div className="cifras">
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Laboratorios entregados</div>
          <div className="numero">
            {datos.entregados} <span className="secundario" style={{ fontSize: "1rem" }}>de {datos.laboratorios}</span>
          </div>
        </div>
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Esperando al docente</div>
          <div className="numero">{datos.esperando}</div>
        </div>
        <div className="tarjeta cifra-tarjeta">
          <div className="secundario">Con nota publicada</div>
          <div className="numero">{datos.publicados}</div>
        </div>
      </div>

      {datos.pendientes.length > 0 && (
        <section className="aviso">
          <strong>Te falta entregar:</strong> {datos.pendientes.map((p) => p.titulo).join(" · ")}.{" "}
          <Link to="/entregas">Subir una entrega</Link>
        </section>
      )}

      {(datos.fortalezas.length > 0 || datos.por_mejorar.length > 0) && (
        <div className="rejilla">
          <section>
            <h2>Lo que mejor dominas</h2>
            <Barras filas={datos.fortalezas.map((c) => ({ nombre: `${c.criterio} · ${c.laboratorio}`, ...c }))} />
          </section>
          <section>
            <h2>Dónde puedes subir más</h2>
            {datos.por_mejorar.length === 0 ? (
              <p className="exito">Todos tus criterios están en Alto. ¡Sigue así!</p>
            ) : (
              <Barras filas={datos.por_mejorar.map((c) => ({ nombre: `${c.criterio} · ${c.laboratorio}`, ...c }))} />
            )}
          </section>
        </div>
      )}

      <div className="fila">
        <Link className="boton" to="/informe">
          Ver mi informe completo
        </Link>
        <Link className="boton secundario" to="/mapa">
          Ver mi mapa mental
        </Link>
      </div>
    </>
  );
}

/** El cerro de Manizales al Nevado: el punto glaciar marca a qué altura va tu promedio. */
function Cerro({ promedio }: { promedio: number | null }) {
  const altura = promedio === null ? null : metros(promedio);
  const y = promedio === null ? 0 : 108 - (Math.max(0, Math.min(5, promedio)) / 5) * 92;
  // x sobre la ladera: la misma proporción que la altura, para que el punto quede en el cerro
  const x = promedio === null ? 0 : 20 + (Math.max(0, Math.min(5, promedio)) / 5) * 180;
  return (
    <svg
      viewBox="0 0 300 120"
      style={{ width: "100%", maxWidth: 360, height: "auto", marginTop: 12 }}
      role="img"
      aria-label={altura === null ? "Cerro sin datos todavía" : `Vas a ${altura.toLocaleString("es-CO")} metros de 5.321`}
    >
      <path d="M0 118 L20 108 L110 62 L150 74 L200 16 L300 118 Z" fill="#dcebe3" />
      <path d="M186 32 L200 16 L214 32 L206 28 L200 34 L193 28 Z" fill="#00b4d8" />
      <text x="4" y="112" fontSize="10" fill="#44564b">
        Manizales 2.150 m
      </text>
      <text x="214" y="12" fontSize="10" fill="#44564b">
        Nevado 5.321 m
      </text>
      {altura !== null && (
        <g>
          <circle cx={x} cy={y} r="6" fill="#0b5d3b" stroke="#ffffff" strokeWidth="2" />
          <text x={x + 10} y={y + 4} fontSize="11" fontWeight="700" fill="#15241c">
            {altura.toLocaleString("es-CO")} m
          </text>
        </g>
      )}
    </svg>
  );
}
