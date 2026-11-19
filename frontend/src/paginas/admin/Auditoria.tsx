// Registro de auditoría (RF-15): quién hizo qué y cuándo. Nadie lo edita desde la app.
import { useEffect, useMemo, useState } from "react";
import { ErrorApi, api, type RegistroAuditoria } from "../../api";
import { Estado } from "../../componentes";

const cuando = (iso: string) =>
  new Date(iso).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Auditoria() {
  const [filas, setFilas] = useState<RegistroAuditoria[] | null>(null);
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState("");

  useEffect(() => {
    api<RegistroAuditoria[]>("/api/auditoria?limite=200")
      .then(setFilas)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la auditoría."));
  }, []);

  const visibles = useMemo(() => {
    const texto = filtro.trim().toLowerCase();
    if (!filas || !texto) return filas ?? [];
    return filas.filter((f) => `${f.accion} ${f.entidad}`.toLowerCase().includes(texto));
  }, [filas, filtro]);

  if (!filas) return <Estado cargando={!error} error={error} />;

  return (
    <>
      <p className="secundario">Las últimas {filas.length} acciones. Cada cambio de datos se anota en la misma operación que lo hace.</p>
      <label className="campo" style={{ maxWidth: 360 }}>
        Filtrar por acción o entidad
        <input type="search" value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="evaluacion_publicada, sesion…" />
      </label>
      <div className="tabla-scroll">
        <table>
          <thead>
            <tr>
              <th>Cuándo</th>
              <th>Acción</th>
              <th>Entidad</th>
              <th>Quién</th>
              <th>Detalle</th>
            </tr>
          </thead>
          <tbody>
            {visibles.map((f) => (
              <tr key={f.id}>
                <td style={{ whiteSpace: "nowrap" }}>{cuando(f.fecha)}</td>
                <td>
                  <code>{f.accion}</code>
                </td>
                <td>{f.entidad}</td>
                <td>{f.usuario_id ? <code>{f.usuario_id.slice(0, 8)}</code> : "—"}</td>
                <td>
                  <code style={{ wordBreak: "break-word" }}>
                    {Object.keys(f.detalle).length ? JSON.stringify(f.detalle) : "—"}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
