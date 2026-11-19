import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Rol, type Sesion } from "./api";
import { Curvas } from "./componentes";
import Admin from "./paginas/Admin";
import Bandeja from "./paginas/Bandeja";
import Bitacora from "./paginas/Bitacora";
import Laboratorio from "./paginas/Laboratorio";
import Laboratorios from "./paginas/Laboratorios";
import Clave from "./paginas/Clave";
import Entregas from "./paginas/Entregas";
import Informe from "./paginas/Informe";
import Inicio from "./paginas/Inicio";
import Mapa from "./paginas/Mapa";
import MiTablero from "./paginas/MiTablero";
import Proyecto from "./paginas/Proyecto";
import Publicada from "./paginas/Publicada";
import Revision from "./paginas/Revision";
import Tablero from "./paginas/Tablero";

/** Qué ve cada rol en el menú (el backend vuelve a revisar el rol en cada ruta). */
const MENU: Record<Rol, { a: string; texto: string }[]> = {
  estudiante: [
    { a: "/mi-tablero", texto: "Mi tablero" },
    { a: "/entregas", texto: "Mis entregas" },
    { a: "/informe", texto: "Mi informe" },
    { a: "/mapa", texto: "Mapa mental" },
  ],
  docente: [
    { a: "/tablero", texto: "Tablero" },
    { a: "/laboratorios", texto: "Laboratorios" },
    { a: "/bandeja", texto: "Bandeja" },
  ],
  administrador: [{ a: "/admin", texto: "Administración" }],
};

export default function App() {
  const [sesion, setSesion] = useState<Sesion | null | undefined>(undefined);
  const navegar = useNavigate();

  useEffect(() => {
    api<Sesion>("/api/yo")
      .then(setSesion)
      .catch(() => setSesion(null));
  }, []);

  async function salir() {
    await api("/api/sesion", { method: "DELETE" }).catch(() => undefined);
    setSesion(null);
    navegar("/");
  }

  const rol = sesion?.usuario.rol;
  const clave = sesion?.debe_cambiar_contrasena;
  // Con clave temporal solo se puede ir a cambiarla.
  const solo = (r: Rol, pagina: React.ReactNode) =>
    !sesion ? <Navigate to="/" /> : clave ? <Navigate to="/clave" /> : rol === r ? pagina : <Navigate to="/" />;

  return (
    <>
      <header className="encabezado">
        <Curvas />
        <div className="barra">
          <p className="marca">
            Asesor pedagógico <span>inteligente</span>
          </p>
          <nav aria-label="Menú principal">
            {sesion &&
              !clave &&
              rol &&
              MENU[rol].map((m) => (
                <NavLink key={m.a} to={m.a} className={({ isActive }) => (isActive ? "activo" : "")}>
                  {m.texto}
                </NavLink>
              ))}
            {sesion ? (
              <>
                <NavLink to="/clave" className={({ isActive }) => (isActive ? "activo" : "")}>
                  Contraseña
                </NavLink>
                <button type="button" onClick={salir}>
                  Salir ({sesion.usuario.nombre})
                </button>
              </>
            ) : (
              <NavLink to="/" end className={({ isActive }) => (isActive ? "activo" : "")}>
                Entrar
              </NavLink>
            )}
          </nav>
        </div>
      </header>
      <main className="pagina">
        {sesion === undefined ? (
          <p className="secundario">Cargando…</p>
        ) : (
          <Routes>
            <Route path="/" element={<Inicio sesion={sesion} alEntrar={setSesion} />} />
            <Route
              path="/clave"
              element={sesion ? <Clave sesion={sesion} alCambiar={setSesion} /> : <Navigate to="/" />}
            />
            <Route path="/mi-tablero" element={solo("estudiante", <MiTablero nombre={sesion?.usuario.nombre ?? ""} />)} />
            <Route path="/entregas" element={solo("estudiante", <Entregas />)} />
            <Route path="/informe" element={solo("estudiante", <Informe estudianteId={sesion?.usuario.id ?? ""} />)} />
            <Route path="/mapa" element={solo("estudiante", <Mapa estudianteId={sesion?.usuario.id ?? ""} />)} />
            <Route path="/publicada/:id" element={solo("estudiante", <Publicada />)} />
            <Route path="/bandeja" element={solo("docente", <Bandeja />)} />
            <Route path="/revision/:id" element={solo("docente", <Revision />)} />
            <Route path="/tablero" element={solo("docente", <Tablero />)} />
            <Route path="/laboratorios" element={solo("docente", <Laboratorios />)} />
            <Route path="/laboratorios/:id" element={solo("docente", <Laboratorio />)} />
            <Route path="/admin" element={solo("administrador", <Admin yo={sesion?.usuario.id ?? ""} seccion="usuarios" />)} />
            <Route path="/admin/ia" element={solo("administrador", <Admin yo={sesion?.usuario.id ?? ""} seccion="ia" />)} />
            <Route path="/admin/costos" element={solo("administrador", <Admin yo={sesion?.usuario.id ?? ""} seccion="costos" />)} />
            <Route
              path="/admin/auditoria"
              element={solo("administrador", <Admin yo={sesion?.usuario.id ?? ""} seccion="auditoria" />)}
            />
            <Route path="/proyecto" element={<Proyecto />} />
            <Route path="/equipo" element={<Proyecto />} />
            <Route path="/bitacora" element={<Bitacora />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        )}
      </main>
      {/* Lo público del proyecto (RF-18, RF-22) va aquí abajo, no en el menú de trabajo. */}
      <footer className="pie">
        <span>Asesor Pedagógico Inteligente · Profundización I — IA · Universidad de Manizales</span>
        <nav aria-label="Sobre el proyecto">
          <Link to="/proyecto">Proyecto y equipo</Link>
          <Link to="/bitacora">Cómo usamos la IA</Link>
        </nav>
      </footer>
    </>
  );
}
