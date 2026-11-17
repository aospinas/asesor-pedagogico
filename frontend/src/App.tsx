import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Sesion } from "./api";
import Bandeja from "./paginas/Bandeja";
import Bitacora from "./paginas/Bitacora";
import Informe from "./paginas/Informe";
import Inicio from "./paginas/Inicio";
import Mapa from "./paginas/Mapa";
import Proyecto from "./paginas/Proyecto";
import Publicada from "./paginas/Publicada";
import Revision from "./paginas/Revision";

export default function App() {
  const [sesion, setSesion] = useState<Sesion | null | undefined>(undefined);
  const navegar = useNavigate();

  useEffect(() => {
    api<Sesion>("/api/yo")
      .then(setSesion)
      .catch(() => setSesion(null));
  }, []);

  async function salir() {
    await api("/api/sesion", { method: "DELETE" });
    setSesion(null);
    navegar("/");
  }

  const rol = sesion?.usuario.rol;
  return (
    <>
      <header className="encabezado">
        <svg viewBox="0 0 1200 90" aria-hidden="true">
          <path d="M0 70 C 200 20, 400 80, 600 40 C 800 0, 1000 60, 1200 20 V 90 H 0 Z" fill="#084a2f" />
          <path d="M0 78 C 220 40, 480 88, 700 50 C 900 20, 1060 70, 1200 36 V 90 H 0 Z" fill="#063c26" />
          <path d="M760 18 C 820 8, 880 8, 940 18 C 900 4, 820 4, 760 18 Z" fill="#00b4d8" />
        </svg>
        <div className="barra">
          <p className="marca">
            Asesor pedagógico <span>inteligente</span>
          </p>
          <nav>
            <Link to="/proyecto">Proyecto</Link>
            <Link to="/bitacora">Bitácora</Link>
            {rol === "docente" && <Link to="/bandeja">Revisión</Link>}
            {rol === "estudiante" && <Link to="/informe">Informe</Link>}
            {rol === "estudiante" && <Link to="/mapa">Mapa</Link>}
            {sesion && (
              <button className="salir" onClick={salir}>
                Salir
              </button>
            )}
          </nav>
        </div>
      </header>
      <main className="pagina">
        {sesion === undefined ? (
          <p>Cargando…</p>
        ) : (
          <Routes>
            <Route path="/" element={<Inicio sesion={sesion} alEntrar={setSesion} />} />
            <Route path="/proyecto" element={<Proyecto />} />
            <Route path="/bitacora" element={<Bitacora />} />
            <Route path="/bandeja" element={rol === "docente" ? <Bandeja /> : <Navigate to="/" />} />
            <Route path="/revision/:id" element={rol === "docente" ? <Revision /> : <Navigate to="/" />} />
            <Route
              path="/informe"
              element={rol === "estudiante" ? <Informe estudianteId={sesion.usuario.id} /> : <Navigate to="/" />}
            />
            <Route
              path="/mapa"
              element={rol === "estudiante" ? <Mapa estudianteId={sesion.usuario.id} /> : <Navigate to="/" />}
            />
            <Route path="/publicada/:id" element={sesion ? <Publicada /> : <Navigate to="/" />} />
          </Routes>
        )}
      </main>
    </>
  );
}
