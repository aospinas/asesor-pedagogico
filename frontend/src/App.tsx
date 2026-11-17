import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Rol, type Sesion } from "./api";
import { Curvas } from "./componentes";
import Bandeja from "./paginas/Bandeja";
import Clave from "./paginas/Clave";
import Entregas from "./paginas/Entregas";
import Informe from "./paginas/Informe";
import Inicio from "./paginas/Inicio";
import Mapa from "./paginas/Mapa";
import Publicada from "./paginas/Publicada";
import Revision from "./paginas/Revision";

/** Qué ve cada rol en el menú (el backend vuelve a revisar el rol en cada ruta). */
const MENU: Record<Rol, { a: string; texto: string }[]> = {
  estudiante: [
    { a: "/entregas", texto: "Mis entregas" },
    { a: "/informe", texto: "Mi informe" },
    { a: "/mapa", texto: "Mapa mental" },
  ],
  docente: [{ a: "/bandeja", texto: "Bandeja" }],
  administrador: [],
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
          {sesion && (
            <nav aria-label="Menú principal">
              {!clave &&
                rol &&
                MENU[rol].map((m) => (
                  <NavLink key={m.a} to={m.a} className={({ isActive }) => (isActive ? "activo" : "")}>
                    {m.texto}
                  </NavLink>
                ))}
              <NavLink to="/clave" className={({ isActive }) => (isActive ? "activo" : "")}>
                Contraseña
              </NavLink>
              <button type="button" onClick={salir}>
                Salir ({sesion.usuario.nombre})
              </button>
            </nav>
          )}
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
            <Route path="/entregas" element={solo("estudiante", <Entregas />)} />
            <Route path="/informe" element={solo("estudiante", <Informe estudianteId={sesion?.usuario.id ?? ""} />)} />
            <Route path="/mapa" element={solo("estudiante", <Mapa estudianteId={sesion?.usuario.id ?? ""} />)} />
            <Route path="/publicada/:id" element={solo("estudiante", <Publicada />)} />
            <Route path="/bandeja" element={solo("docente", <Bandeja />)} />
            <Route path="/revision/:id" element={solo("docente", <Revision />)} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        )}
      </main>
    </>
  );
}
