// Configuración de IA (RF-19, CU-08). La llave nunca pasa por aquí: vive en LLM_API_KEY, en Render.
import { type FormEvent, useEffect, useState } from "react";
import { ErrorApi, api, enviarJson, type ConfigIAVista, type Proveedor, type PruebaConexion } from "../../api";
import { Estado } from "../../componentes";
import { fecha } from "../../util";

const DIRECCION: Record<Proveedor, string> = {
  openai: "https://api.openai.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  ollama: "http://localhost:11434/v1",
};
const NOMBRE: Record<Proveedor, string> = { openai: "OpenAI", openrouter: "OpenRouter", ollama: "Ollama (local)" };
const ORIGEN = {
  base: "La eligió el administrador",
  entorno: "Sale de las variables de Render (LLM_*)",
  sin_configurar: "Sin configurar",
};
const mensaje = (e: unknown) => (e instanceof ErrorApi ? e.message : "No se pudo conectar. Revisa tu internet.");

export default function ConfigIA() {
  const [vista, setVista] = useState<ConfigIAVista | null>(null);
  const [error, setError] = useState("");
  const [proveedor, setProveedor] = useState<Proveedor>("openai");
  const [modelo, setModelo] = useState("");
  const [direccion, setDireccion] = useState(DIRECCION.openai);
  const [precioEntrada, setPrecioEntrada] = useState("");
  const [precioSalida, setPrecioSalida] = useState("");
  const [aviso, setAviso] = useState("");
  const [prueba, setPrueba] = useState<PruebaConexion | null>(null);
  const [ocupado, setOcupado] = useState(false);

  function mostrar(v: ConfigIAVista) {
    setVista(v);
    setProveedor(v.proveedor);
    setModelo(v.modelo);
    setDireccion(v.base_url || DIRECCION[v.proveedor]);
    setPrecioEntrada(String(v.precio_entrada_usd));
    setPrecioSalida(String(v.precio_salida_usd));
  }

  useEffect(() => {
    api<ConfigIAVista>("/api/config-ia")
      .then(mostrar)
      .catch((e) => setError(mensaje(e)));
  }, []);

  function cambiarProveedor(p: Proveedor) {
    setProveedor(p);
    setDireccion(DIRECCION[p]);
  }

  async function guardar(evento: FormEvent) {
    evento.preventDefault();
    setAviso("");
    setPrueba(null);
    setOcupado(true);
    const conPrecios = precioEntrada.trim() !== "" && precioSalida.trim() !== "";
    try {
      const v = await api<ConfigIAVista>(
        "/api/config-ia",
        enviarJson(
          {
            proveedor,
            modelo,
            base_url: direccion,
            precio_entrada_usd: conPrecios ? Number(precioEntrada) : null,
            precio_salida_usd: conPrecios ? Number(precioSalida) : null,
          },
          "PUT",
        ),
      );
      mostrar(v);
      setAviso("Guardado. La próxima evaluación usará este modelo y quedará registrado en su traza.");
    } catch (e) {
      setAviso(mensaje(e));
    } finally {
      setOcupado(false);
    }
  }

  async function probar() {
    setAviso("");
    setPrueba(null);
    setOcupado(true);
    try {
      setPrueba(await api<PruebaConexion>("/api/config-ia/probar", { method: "POST" }));
    } catch (e) {
      setAviso(mensaje(e));
    } finally {
      setOcupado(false);
    }
  }

  if (!vista) return <Estado cargando={!error} error={error} />;

  return (
    <>
      <section className="tarjeta">
        <h2 style={{ marginTop: 0 }}>Modelo en uso</h2>
        <p>
          <strong>{NOMBRE[vista.proveedor]}</strong> · {vista.modelo || "—"}
        </p>
        <p className="secundario">
          {ORIGEN[vista.origen]}
          {vista.fecha && ` · desde el ${fecha(vista.fecha)}`}
        </p>
        <p>
          {vista.llave_configurada ? (
            <span className="etiqueta">✓ La llave está configurada en el servidor</span>
          ) : (
            <span className="etiqueta alerta">Falta la llave: ponla en la variable LLM_API_KEY de Render</span>
          )}
        </p>
        <p className="secundario">
          Precio por millón de tokens: entrada US$ {vista.precio_entrada_usd} · salida US$ {vista.precio_salida_usd}
        </p>
        <button className="boton secundario" type="button" onClick={probar} disabled={ocupado}>
          {ocupado ? "Probando…" : "Probar conexión"}
        </button>
        {prueba && (
          <p className={prueba.ok ? "exito" : "error"} role="status" style={{ marginTop: 12 }}>
            {prueba.ok ? "✓" : "✗"} {prueba.mensaje} ({NOMBRE[prueba.proveedor]} · {prueba.modelo})
          </p>
        )}
      </section>

      <form className="tarjeta" onSubmit={guardar}>
        <h2 style={{ marginTop: 0 }}>Cambiar de proveedor o de modelo</h2>
        <div className="rejilla">
          <label className="campo">
            Proveedor
            <select value={proveedor} onChange={(e) => cambiarProveedor(e.target.value as Proveedor)}>
              {Object.entries(NOMBRE).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="campo">
            Modelo
            <input value={modelo} onChange={(e) => setModelo(e.target.value)} maxLength={120} required />
          </label>
          <label className="campo">
            Dirección
            <span className="ayuda">
              {proveedor === "ollama"
                ? "Solo equipos permitidos en OLLAMA_HOSTS_PERMITIDOS, puerto 11434 y /v1."
                : "Es fija para este proveedor."}
            </span>
            <input
              value={direccion}
              onChange={(e) => setDireccion(e.target.value)}
              readOnly={proveedor !== "ollama"}
              maxLength={300}
              required
            />
          </label>
        </div>
        <div className="rejilla">
          <label className="campo">
            Precio de entrada (US$ por millón de tokens)
            <input type="number" min={0} max={1000} step="any" value={precioEntrada} onChange={(e) => setPrecioEntrada(e.target.value)} />
          </label>
          <label className="campo">
            Precio de salida (US$ por millón de tokens)
            <input type="number" min={0} max={1000} step="any" value={precioSalida} onChange={(e) => setPrecioSalida(e.target.value)} />
          </label>
        </div>
        <p className="ayuda">Pon los dos precios o deja los dos vacíos (se usan los de LLM_PRECIO_*). Con Ollama cuesta 0.</p>
        {aviso && (
          <p className="aviso" role="status">
            {aviso}
          </p>
        )}
        <button className="boton" type="submit" disabled={ocupado}>
          Guardar configuración
        </button>
      </form>
    </>
  );
}
