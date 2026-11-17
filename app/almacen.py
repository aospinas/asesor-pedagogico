"""Dónde viven los archivos de las entregas (RNF-07).

- `local`: una carpeta del PC. Para desarrollo y pruebas.
- `supabase`: Supabase Storage, en un bucket privado. Para Render.

Reglas:
- La ruta de cada archivo la arma el backend (`entregas/<id>/<id>`); nunca sale del
  nombre que manda el estudiante, así que no puede salirse de su carpeta.
- Se descarga solo con un enlace firmado que vence pronto. En Supabase lo firma
  Supabase; en local lo firma la app y se abre en `GET /api/archivos/{token}`.
- La llave de Supabase solo va a la dirección del proyecto (`https://<ref>.supabase.co`)
  y nunca sale en errores ni registros.
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx
import jwt

from app.config import ajustes

registro = logging.getLogger("asesor.almacen")

VIGENCIA_ENLACE_SEG = 300  # 5 minutos
AUDIENCIA_ARCHIVO = "archivo"  # así un token de archivo nunca sirve como sesión, ni al revés
PATRON_SUPABASE = re.compile(r"^https://[a-z0-9]{10,40}\.supabase\.co$")
PATRON_RUTA = re.compile(r"^entregas/[0-9a-f-]{36}/[0-9a-f-]{36}$")


class AlmacenNoDisponible(Exception):
    """El almacenamiento no está configurado o no respondió."""


class Almacen(Protocol):
    def guardar(self, ruta: str, contenido: bytes, tipo_mime: str) -> None: ...
    def leer(self, ruta: str) -> bytes: ...
    def borrar(self, ruta: str) -> None: ...
    def enlace(self, ruta: str, nombre: str) -> str: ...


def ruta_de(entrega_id: uuid.UUID, evidencia_id: uuid.UUID) -> str:
    return f"entregas/{entrega_id}/{evidencia_id}"


def _revisar_ruta(ruta: str) -> str:
    if not PATRON_RUTA.match(ruta):
        raise ValueError("Ruta de archivo no válida.")
    return ruta


# ---------- Local ----------


class AlmacenLocal:
    def __init__(self, carpeta: str | Path):
        self.carpeta = Path(carpeta).resolve()

    def _camino(self, ruta: str) -> Path:
        camino = (self.carpeta / _revisar_ruta(ruta)).resolve()
        if not camino.is_relative_to(self.carpeta):  # segunda defensa: nunca fuera de la carpeta
            raise ValueError("Ruta de archivo no válida.")
        return camino

    def guardar(self, ruta: str, contenido: bytes, tipo_mime: str) -> None:
        camino = self._camino(ruta)
        camino.parent.mkdir(parents=True, exist_ok=True)
        with open(camino, "xb") as f:  # "x": nunca pisa un archivo que ya existe
            f.write(contenido)

    def leer(self, ruta: str) -> bytes:
        return self._camino(ruta).read_bytes()

    def borrar(self, ruta: str) -> None:
        self._camino(ruta).unlink(missing_ok=True)

    def enlace(self, ruta: str, nombre: str) -> str:
        datos = {
            "ruta": _revisar_ruta(ruta),
            "nombre": nombre,
            "aud": AUDIENCIA_ARCHIVO,
            "exp": datetime.now(UTC) + timedelta(seconds=VIGENCIA_ENLACE_SEG),
        }
        token = jwt.encode(datos, ajustes().jwt_secreto, algorithm="HS256")
        return f"/api/archivos/{token}"


def leer_token(token: str) -> dict | None:
    """Datos de un enlace local firmado, o None si es falso o ya venció."""
    try:
        datos = jwt.decode(
            token,
            ajustes().jwt_secreto,
            algorithms=["HS256"],
            audience=AUDIENCIA_ARCHIVO,
            options={"require": ["ruta", "nombre", "aud", "exp"]},
        )
        _revisar_ruta(datos["ruta"])
        return datos
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None


# ---------- Supabase ----------


class AlmacenSupabase:
    def __init__(self, url: str, llave: str, bucket: str, cliente: httpx.Client | None = None):
        # Los espacios y saltos de línea de los bordes se quitan: se cuelan al pegar el valor
        # en Render. Después se exige la forma exacta (fullmatch: nada antes ni después).
        url = url.strip().rstrip("/")
        llave = llave.strip()
        # El mensaje dice QUÉ variable falla, nunca su valor (va al registro del servidor).
        if not PATRON_SUPABASE.fullmatch(url):
            raise AlmacenNoDisponible(
                "Supabase Storage no está configurado: SUPABASE_URL debe ser exactamente "
                "https://<ref>.supabase.co (Project Settings > Data API > Project URL)."
            )
        if not llave:
            raise AlmacenNoDisponible("Supabase Storage no está configurado: falta SUPABASE_SERVICE_KEY.")
        self.base = url + "/storage/v1"
        self.bucket = bucket
        self._llave = llave
        self.cliente = cliente or httpx.Client(timeout=30, follow_redirects=False)

    def _cabeceras(self, extra: dict | None = None) -> dict:
        return {"Authorization": f"Bearer {self._llave}", "apikey": self._llave, **(extra or {})}

    def _pedir(self, metodo: str, camino: str, **datos) -> httpx.Response:
        try:
            respuesta = self.cliente.request(metodo, self.base + camino, **datos)
        except httpx.HTTPError as error:
            registro.error("Supabase Storage no respondió: %s", type(error).__name__)
            raise AlmacenNoDisponible("El almacenamiento de archivos no respondió.") from None
        if respuesta.status_code >= 400:
            # Solo el código: la respuesta podría traer datos internos.
            registro.error("Supabase Storage respondió %s en %s", respuesta.status_code, metodo)
            raise AlmacenNoDisponible("El almacenamiento de archivos no respondió.")
        return respuesta

    def guardar(self, ruta: str, contenido: bytes, tipo_mime: str) -> None:
        self._pedir(
            "POST",
            f"/object/{self.bucket}/{_revisar_ruta(ruta)}",
            content=contenido,
            headers=self._cabeceras({"Content-Type": tipo_mime, "x-upsert": "false"}),
        )

    def leer(self, ruta: str) -> bytes:
        return self._pedir(
            "GET", f"/object/authenticated/{self.bucket}/{_revisar_ruta(ruta)}", headers=self._cabeceras()
        ).content

    def borrar(self, ruta: str) -> None:
        self._pedir(
            "DELETE",
            f"/object/{self.bucket}",
            json={"prefixes": [_revisar_ruta(ruta)]},
            headers=self._cabeceras(),
        )

    def enlace(self, ruta: str, nombre: str) -> str:
        respuesta = self._pedir(
            "POST",
            f"/object/sign/{self.bucket}/{_revisar_ruta(ruta)}",
            json={"expiresIn": VIGENCIA_ENLACE_SEG},
            headers=self._cabeceras(),
        )
        try:
            datos = respuesta.json()
            firmado = datos.get("signedURL") or datos.get("signedUrl")
        except (ValueError, AttributeError):  # no era JSON, o no era un objeto
            firmado = None
        if not isinstance(firmado, str) or not firmado.startswith("/object/sign/"):
            raise AlmacenNoDisponible("El almacenamiento de archivos no respondió.")
        separador = "&" if "?" in firmado else "?"
        return f"{self.base}{firmado}{separador}download={quote(nombre)}"


# ---------- El que usa la app ----------


@cache
def obtener_almacen() -> Almacen:
    """El almacén configurado, uno solo para toda la app: así hay una sola conexión a
    Supabase y no una nueva (que nunca se cerraba) en cada petición.

    Si falla (por ejemplo, Supabase sin configurar), no queda guardado: se vuelve a
    intentar en la siguiente petición. Las pruebas lo cambian por una carpeta temporal."""
    return crear_almacen()


def crear_almacen() -> Almacen:
    a = ajustes()
    if a.almacen == "supabase":
        return AlmacenSupabase(a.supabase_url, a.supabase_service_key.get_secret_value(), a.supabase_bucket)
    if a.en_produccion:
        # En Render el disco se borra en cada despliegue: los archivos se perderían.
        raise AlmacenNoDisponible("En producción los archivos deben ir a Supabase (ALMACEN=supabase).")
    return AlmacenLocal(a.almacen_carpeta)
