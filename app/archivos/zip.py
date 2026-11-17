"""Leer el código de un ZIP sin descomprimirlo en disco y sin ejecutar nada (RF-09, OWASP A08).

Defensas:
- Rutas que se salen de la carpeta (zip slip), absolutas o con unidad de Windows: se rechaza el ZIP.
- Enlaces simbólicos y archivos cifrados: se rechaza el ZIP.
- Topes de cantidad de archivos, de tamaño descomprimido total y por archivo. Lo que
  dice el ZIP sobre su tamaño puede mentir, así que también se cuenta lo leído de verdad.
- Solo se guarda el texto de archivos de texto; los binarios se anotan como omitidos.
"""

import io
import logging
import stat
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field

from app.archivos import ArchivoNoValido, megas

MAXIMO_ARCHIVOS = 500
MAXIMO_DESCOMPRIMIDO = 20 * 1024 * 1024  # todo el ZIP abierto
MAXIMO_POR_ARCHIVO = 512 * 1024  # un archivo de texto más grande se omite
MAXIMO_TEXTO = 5 * 1024 * 1024  # lo que se guarda en la base entre todos los archivos

# Carpetas que no son código del estudiante
CARPETAS_IGNORADAS = ("__pycache__/", ".git/", "node_modules/", ".venv/", "venv/", ".ipynb_checkpoints/")

ERRORES_ZIP = (
    zipfile.BadZipFile,
    RuntimeError,
    NotImplementedError,
    EOFError,
    zlib.error,
    OSError,
    MemoryError,
    # Un nombre interno marcado como UTF-8 pero con bytes inválidos lanza UnicodeDecodeError,
    # y un índice raro puede dar "negative seek value": los dos son ValueError (4.ª revisión).
    # Ojo: ArchivoNoValido también es ValueError, por eso cada lector lo vuelve a lanzar antes.
    ValueError,
    # Un desplazamiento ZIP64 de 2^63 en el índice da OverflowError al abrir la entrada
    # (5.ª revisión). Además revisar_entradas lo rechaza antes.
    ArithmeticError,
)
# Red de seguridad (6.ª revisión): cualquier OTRA excepción al leer un archivo ajeno también
# se trata como archivo dañado, pero queda en el registro del servidor con su tipo (7.ª
# revisión): así un error de nuestro propio código no se confunde con un archivo dañado
# del estudiante sin que nadie se entere. Se usa con error_inesperado().
ERRORES_DESCONOCIDOS = (Exception,)
# Solo sin comprimir y "deflate" (los normales). LZMA, bzip2 o zstd pueden pedir mucha
# memoria al abrirse aunque se lea poco (revisión de seguridad, D-17).
COMPRESIONES_PERMITIDAS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
# Caracteres que no van en una ruta: Windows no los acepta y podrían colarse en el prompt
PROHIBIDOS_EN_RUTA = frozenset('\\:<>|"*?')
NO_ABRE = "No se pudo abrir el ZIP."
# No se repite el nombre que mandó el estudiante (regla del proyecto: los errores no
# devuelven lo que la persona escribió); se dice qué buscar.
RUTA_NO_PERMITIDA = (
    "El ZIP trae nombres de archivo o carpeta que no se permiten: con '..', que empiezan "
    'con "/", con "./" o "//" de sobra, con espacios al inicio o al final, que tienen '
    'caracteres como < > : | ? * " \\, caracteres invisibles (los que a veces se pegan al '
    "copiar texto) o más de 255 letras. Cámbialos y vuelve a subirlo."
)
RUTA_REPETIDA = (
    "El ZIP trae dos archivos con el mismo nombre (o casi el mismo: uno en mayúsculas, o con "
    "letras anchas que se ven iguales). Deja uno solo y vuelve a subirlo."
)

registro = logging.getLogger("asesor.archivos")


def error_inesperado(lector: str, error: Exception) -> None:
    """Deja en el registro el tipo de una excepción que no se esperaba al leer un archivo.
    Solo el tipo: nada del contenido del archivo."""
    registro.warning("Error inesperado leyendo %s: %s", lector, type(error).__name__)


@dataclass
class ArchivoCodigo:
    ruta: str
    texto: str


@dataclass
class CodigoExtraido:
    arbol: list[str] = field(default_factory=list)
    archivos: list[ArchivoCodigo] = field(default_factory=list)
    omitidos: list[dict[str, str]] = field(default_factory=list)

    def como_json(self) -> dict:
        return {
            "arbol": self.arbol,
            "archivos": [{"ruta": a.ruta, "texto": a.texto} for a in self.archivos],
            "omitidos": self.omitidos,
        }


def es_zip(contenido: bytes) -> bool:
    return contenido.startswith(b"PK\x03\x04")


def revisar_entradas(infos: list[zipfile.ZipInfo], tamano: int, mensaje: str = NO_ABRE) -> None:
    """Cada entrada tiene que empezar dentro del archivo. Un índice que apunta más allá (por
    ejemplo con un desplazamiento ZIP64 de 2^63) se rechaza antes de abrir nada."""
    if any(not 0 <= info.header_offset < tamano for info in infos):
        raise ArchivoNoValido(mensaje)


def ruta_limpia(nombre: str) -> str:
    """La ruta normalizada con NFKC: es la que se revisa y la que se guarda.

    Así '＜entrega＞' (ancho completo) se vuelve '<entrega>' y se rechaza, '．．' se vuelve
    '..' y se rechaza, pero 'Taller 1º.py' (que queda 'Taller 1o.py'), 'x².py' o los
    espacios especiales de macOS pasan, y las tildes descompuestas de los ZIP de Mac se
    componen (6.ª revisión: rechazar todo lo que cambiara dejaba fuera nombres normales)."""
    return unicodedata.normalize("NFKC", nombre)


def ruta_segura(nombre: str) -> bool:
    """Una ruta dentro del ZIP que no puede salirse de la carpeta ni traer caracteres raros.
    Se revisa la forma normalizada (ruta_limpia), que es la que llega al evaluador."""
    nombre = ruta_limpia(nombre)
    if not nombre or nombre.startswith("/") or len(nombre) > 255:
        return False
    if any(c in PROHIBIDOS_EN_RUTA or es_invisible(c) for c in nombre):
        return False
    # Cada tramo tiene que ser un nombre de verdad: sin '..' (salirse de la carpeta), sin '.'
    # ni vacíos ('./main.py', 'a//main.py' apuntan al mismo archivo que 'main.py' y 'a/main.py')
    # y sin espacios al inicio o al final ('main.py ' se ve igual que 'main.py'). La '/' final
    # de las carpetas no cuenta como tramo vacío.
    tramos = (nombre[:-1] if nombre.endswith("/") else nombre).split("/")
    return all(t not in {"", ".", ".."} and t == t.strip() for t in tramos)


def es_invisible(caracter: str) -> bool:
    """Controles (saltos de línea, NUL...), caracteres de formato invisibles (como los que
    invierten el texto, U+202E, o los de ancho cero), los saltos de línea y de párrafo de
    Unicode (U+2028, U+2029) y los caracteres privados o sin asignar."""
    return unicodedata.category(caracter) in {"Cc", "Cf", "Zl", "Zp", "Co", "Cn"}


_FIN_DE_INDICE = b"PK\x05\x06"
_LOCALIZADOR_ZIP64 = b"PK\x06\x07"
_BYTES_POR_ENTRADA = 400  # cabecera de 46 bytes + nombre de hasta 255 + extras, con holgura


def revisar_indice(contenido: bytes, maximo_entradas: int) -> None:
    """Revisa el índice del ZIP ANTES de abrirlo con zipfile (revisión de seguridad, D-17).

    zipfile lee el índice completo al abrir el archivo: un ZIP de 14 MB con 300.000
    entradas falsas pedía 149 MB antes de que se pudiera contar. Aquí se lee solo el
    registro final (22 bytes), que dice cuántas entradas hay y cuánto pesa el índice."""
    inicio = contenido.rfind(_FIN_DE_INDICE, max(0, len(contenido) - 65_557))
    if inicio < 0 or len(contenido) < inicio + 22:
        raise ArchivoNoValido(NO_ABRE)
    # ZIP64 no hace falta para estos tamaños, y si viene, zipfile usa SU registro e ignora
    # el normal: un registro normal que dice "1 entrada" no serviría de nada (3.ª revisión).
    if inicio >= 20 and contenido[inicio - 20 : inicio - 16] == _LOCALIZADOR_ZIP64:
        raise ArchivoNoValido(NO_ABRE)
    entradas = int.from_bytes(contenido[inicio + 10 : inicio + 12], "little")
    peso_indice = int.from_bytes(contenido[inicio + 12 : inicio + 16], "little")
    desplazamiento = int.from_bytes(contenido[inicio + 16 : inicio + 20], "little")
    if entradas == 0xFFFF or peso_indice == 0xFFFFFFFF or desplazamiento == 0xFFFFFFFF:
        raise ArchivoNoValido(NO_ABRE)
    if entradas > maximo_entradas or peso_indice > maximo_entradas * _BYTES_POR_ENTRADA:
        raise ArchivoNoValido(f"El archivo comprimido tiene más de {maximo_entradas} partes.")
    # Segunda defensa: el índice debe caber completo antes del registro final.
    if desplazamiento + peso_indice > inicio:
        raise ArchivoNoValido(NO_ABRE)


def _es_enlace(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _texto(datos: bytes) -> str | None:
    """El contenido como texto, o None si parece binario."""
    if b"\x00" in datos[:8192]:
        return None
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def leer_zip(contenido: bytes) -> CodigoExtraido:
    if not es_zip(contenido):
        raise ArchivoNoValido("El código debe venir en un archivo ZIP.")
    revisar_indice(contenido, MAXIMO_ARCHIVOS)
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            infos = z.infolist()
            revisar_entradas(infos, len(contenido))
            if len(infos) > MAXIMO_ARCHIVOS:
                raise ArchivoNoValido(f"El ZIP tiene más de {MAXIMO_ARCHIVOS} archivos.")
            if sum(i.file_size for i in infos) > MAXIMO_DESCOMPRIMIDO:
                raise ArchivoNoValido(f"El ZIP ocupa más de {megas(MAXIMO_DESCOMPRIMIDO)} al abrirlo.")
            for info in infos:
                if not ruta_segura(info.filename):
                    raise ArchivoNoValido(RUTA_NO_PERMITIDA)
                if _es_enlace(info):
                    raise ArchivoNoValido("El ZIP trae enlaces simbólicos, que no se permiten.")
                if info.flag_bits & 0x1:
                    raise ArchivoNoValido("El ZIP tiene contraseña. Súbelo sin contraseña.")
                if info.compress_type not in COMPRESIONES_PERMITIDAS:
                    raise ArchivoNoValido("El ZIP usa una compresión que no se acepta. Comprímelo de nuevo.")
            _revisar_repetidas(infos)
            return _extraer(z, infos)
    except ArchivoNoValido:
        raise
    except ERRORES_ZIP:
        raise ArchivoNoValido(NO_ABRE) from None
    except ERRORES_DESCONOCIDOS as error:
        error_inesperado("un ZIP de código", error)
        raise ArchivoNoValido(NO_ABRE) from None


def _revisar_repetidas(infos: list[zipfile.ZipInfo]) -> None:
    """Dos archivos que quedan con la misma ruta (después de NFKC y sin mirar mayúsculas)
    se rechazan: si no, el evaluador vería dos 'main.py' distintos y una cita a 'main.py'
    no diría a cuál se refiere (7.ª revisión)."""
    vistas: set[str] = set()
    for info in infos:
        if info.is_dir():
            continue
        clave = ruta_limpia(info.filename).casefold()
        if clave in vistas:
            raise ArchivoNoValido(RUTA_REPETIDA)
        vistas.add(clave)


def _extraer(z: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> CodigoExtraido:
    resultado = CodigoExtraido()
    leido = 0
    guardado = 0
    for info in sorted(infos, key=lambda i: ruta_limpia(i.filename)):
        if info.is_dir():
            continue
        ruta = ruta_limpia(info.filename)  # la misma forma que se revisó en ruta_segura
        resultado.arbol.append(ruta)
        if any(f"/{c}" in f"/{ruta}" for c in CARPETAS_IGNORADAS):
            resultado.omitidos.append({"ruta": ruta, "motivo": "carpeta ignorada"})
            continue
        if info.file_size > MAXIMO_POR_ARCHIVO:
            resultado.omitidos.append({"ruta": ruta, "motivo": "muy grande"})
            continue
        with z.open(info) as f:
            datos = f.read(MAXIMO_POR_ARCHIVO + 1)
        leido += len(datos)
        # zipfile ya no lee más de lo que el ZIP declara (y revisa el CRC); esta cuenta
        # es una defensa extra por si algún día eso cambia.
        if leido > MAXIMO_DESCOMPRIMIDO:
            raise ArchivoNoValido(f"El ZIP ocupa más de {megas(MAXIMO_DESCOMPRIMIDO)} al abrirlo.")
        if len(datos) > MAXIMO_POR_ARCHIVO:
            resultado.omitidos.append({"ruta": ruta, "motivo": "muy grande"})
            continue
        texto = _texto(datos)
        if texto is None:
            resultado.omitidos.append({"ruta": ruta, "motivo": "binario"})
            continue
        if guardado + len(texto) > MAXIMO_TEXTO:
            resultado.omitidos.append({"ruta": ruta, "motivo": "límite de texto"})
            continue
        guardado += len(texto)
        resultado.archivos.append(ArchivoCodigo(ruta=ruta, texto=texto))
    return resultado
