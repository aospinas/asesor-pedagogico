"""Entregas de los estudiantes y descarga de sus archivos (RF-07, RF-09, RNF-07).

Al subir:
1. Se revisa que el laboratorio tenga una rúbrica lista; la entrega queda amarrada a ella.
2. Se hace una revisión rápida de los topes por estudiante, para no gastar trabajo.
3. Se pide turno: solo dos subidas a la vez, de principio a fin (leer, procesar y guardar),
   porque el plan gratis de Render tiene 512 MB.
4. Se lee cada archivo con topes, en este orden: informe, código, imágenes, diapositivas
   (al mostrarlos el orden es otro, el de _ORDEN_TIPOS). El tipo se decide por el
   contenido, no por el nombre. Nada del estudiante se ejecuta aquí.
5. Se guardan los archivos en el almacén. Luego, con la fila del estudiante bloqueada en
   la base, se vuelven a contar los topes y se guarda la entrega. Así dos subidas al mismo
   tiempo no se saltan los topes (en SQLite no hay bloqueo de fila; la restricción única
   del informe repetido sí aplica en las dos bases).

El estudiante solo ve lo suyo: si pide algo ajeno recibe 404, igual que si no existiera,
para no revelar qué ids existen (OWASP A01). Esos intentos quedan en la auditoría.
"""

import hashlib
import logging
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import almacen as almacenes
from app.almacen import Almacen, AlmacenLocal, obtener_almacen
from app.api import seguridad
from app.api.laboratorios import buscar_laboratorio
from app.api.seguridad import Actual, Db, limitador, ruta
from app.archivos import ArchivoMuyGrande, ArchivoNoValido, diapositivas, megas, pdf
from app.archivos import zip as lector_zip
from app.auditoria.registro import registrar
from app.esquemas import (
    EnlaceDescarga,
    Entrega,
    EntregaCrear,
    EvidenciaArchivo,
    NombreArchivo,
    Rol,
    TipoEvidencia,
)
from app.modelos import Auditoria, Usuario
from app.modelos import Entrega as EntregaFila
from app.modelos import Evidencia as EvidenciaFila
from app.modelos import RubricaVersion as RubricaVersionFila
from app.rubricas import versiones

registro = logging.getLogger("asesor.entregas")
router = APIRouter()

# Topes por archivo. El tope de toda la petición (30 MB) está en app/main.py.
MAXIMO_INFORME = 10 * 1024 * 1024
MAXIMO_CODIGO = 15 * 1024 * 1024
MAXIMO_IMAGEN = 2 * 1024 * 1024
MAXIMO_IMAGENES = 5
MAXIMO_DIAPOSITIVAS = 10 * 1024 * 1024
MAXIMO_PAGINAS_INFORME = 60
MAXIMO_CARACTERES_INFORME = 300_000
MINIMO_CARACTERES_INFORME = 30

# Topes por estudiante (OWASP LLM10): el plan gratis de Supabase tiene 1 GB.
ENTREGAS_POR_HORA = 5
ENTREGAS_POR_LABORATORIO = 10
MEGAS_POR_DIA = 100
RECHAZOS_POR_HORA = 10  # archivos rechazados: también gastan turno y lector de PDF
SUBIDAS_A_LA_VEZ = 2
ESPERA_TURNO_SEG = 20
LIMITE_POR_USUARIO = "20/minute"  # la clave es el usuario, no la IP (detrás del proxy de Render es la misma)
# Las listas se paginan: un curso entero no se carga de una vez.
LISTA_POR_DEFECTO = 50
LISTA_MAXIMA = 200
AUDITORIA_SIN_REPETIR_SEG = 60
AJENOS_POR_HORA = 20  # filas de acceso_ajeno_denegado por usuario por hora
ENLACES_POR_HORA = 200  # filas de enlace_emitido por usuario por hora
LIMITE_CONSULTAS = "60/minute"  # ver entrega, enlace y portafolio, por usuario

NO_EXISTE = "Esa entrega no existe."
EVIDENCIA_NO_EXISTE = "Ese archivo no existe."
SIN_RUBRICA = "Este laboratorio todavía no tiene una rúbrica lista. Espera a que el docente la publique."
FALTA_CODIGO = "Falta el código: sube un ZIP o pon el enlace de tu repositorio de GitHub."
ENLACE_MALO = (
    "El enlace debe ser un repositorio público de GitHub, como https://github.com/usuario/repositorio."
)
ESCANEADO = (
    "El informe no tiene texto legible (parece escaneado). "
    "Expórtalo a PDF desde Word o Google Docs y vuelve a subirlo."
)
ENLACE_NO_VALIDO = "El enlace no es válido o ya venció. Pide uno nuevo."
MUCHAS_POR_HORA = f"Ya subiste {ENTREGAS_POR_HORA} entregas en la última hora. Espera un rato."
MUCHAS_EN_LABORATORIO = (
    f"Ya tienes {ENTREGAS_POR_LABORATORIO} entregas en este laboratorio, que es el máximo."
)
MUCHOS_MEGAS = f"Ya subiste más de {MEGAS_POR_DIA} MB hoy. Intenta mañana o sube archivos más livianos."
MUCHOS_RECHAZOS = "Varios de tus archivos fueron rechazados en la última hora. Revísalos y espera un rato."
REPETIDA = "Ya subiste este mismo informe en este laboratorio. Si cambiaste algo, vuelve a exportar el PDF."
OCUPADO = "Hay muchas entregas subiéndose en este momento. Intenta de nuevo en un minuto."

_FIRMAS_IMAGEN = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
_SUBIDAS = threading.BoundedSemaphore(SUBIDAS_A_LA_VEZ)
_NOMBRE_ARCHIVO = TypeAdapter(NombreArchivo)
# Orden fijo de los archivos dentro de una entrega
_ORDEN_TIPOS = {t: i for i, t in enumerate(["pdf", "codigo", "diapositivas", "imagen", "video"])}


def _almacen() -> Almacen:
    return obtener_almacen()


AlmacenDep = Annotated[Almacen, Depends(_almacen)]


class _TopeSuperado(Exception):
    def __init__(self, codigo: int, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass
class _Archivo:
    tipo: TipoEvidencia
    nombre: str
    contenido: bytes
    tipo_mime: str
    texto_extraido: dict[str, Any] | None
    resumen: str | None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.contenido).hexdigest()


# ---------- Ayudas ----------


def nombre_visible(nombre: str | None, defecto: str) -> str:
    """El nombre que se muestra. Nunca se usa para guardar el archivo (eso lo arma el backend).

    - Se normaliza con NFKC: las letras "parecidas" (como ＜ ＞ de ancho completo) pasan a
      las normales y así no se cuelan.
    - Se quitan las carpetas y los caracteres invisibles o que invierten el texto (como
      U+202E, que hace que 'a\\u202efdp.exe' se vea como 'aexe.pdf').
    - Los caracteres que no van en una ruta (< > | " * ? :) se cambian por '_'.
    - Si no queda nada que mostrar (por ejemplo '. .'), se usa el nombre por defecto."""
    nombre = unicodedata.normalize("NFKC", nombre or "").replace("\\", "/").rsplit("/", 1)[-1]
    # Fuera los invisibles y los mismos caracteres que no van en una ruta (< > | " * ? :),
    # para que el nombre no pueda parecer una etiqueta en el prompt ni en la pantalla.
    nombre = "".join(
        "_" if c in lector_zip.PROHIBIDOS_EN_RUTA else c for c in nombre if not lector_zip.es_invisible(c)
    )
    anterior = None
    while nombre != anterior:  # ". ." -> " " -> "": se repite hasta que no cambie
        anterior = nombre
        nombre = nombre.strip().strip(".")
    nombre = nombre[:120].strip()
    try:
        return _NOMBRE_ARCHIVO.validate_python(nombre) if nombre else defecto
    except ValidationError:
        return defecto


def _leer(subido: UploadFile, maximo: int, etiqueta: str) -> bytes:
    contenido = subido.file.read(maximo + 1)
    if len(contenido) > maximo:
        raise ArchivoMuyGrande(f"{etiqueta}: pesa más de {megas(maximo)}.")
    if not contenido:
        raise ArchivoNoValido(f"{etiqueta}: el archivo está vacío.")
    return contenido


def _tipo_imagen(contenido: bytes) -> str | None:
    for firma, mime in _FIRMAS_IMAGEN.items():
        if contenido.startswith(firma):
            return mime
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    return None


def _cuantos(cantidad: int, singular: str) -> str:
    return f"{cantidad} {singular}" + ("" if cantidad == 1 else "s")


def _resumen_paginas(paginas: list[str], unidad: str, recortado: bool) -> str:
    con_texto = sum(1 for p in paginas if p.strip())
    resumen = f"{_cuantos(con_texto, unidad)} con texto"
    return resumen + (" (el texto pasaba del tope y se recortó)" if recortado else "")


def a_esquema(entrega: EntregaFila, evidencias: list[EvidenciaFila], numero: int | None) -> Entrega:
    ordenadas = sorted(evidencias, key=lambda e: (_ORDEN_TIPOS.get(e.tipo, 99), e.nombre, str(e.id)))
    return Entrega(
        id=entrega.id,
        estudiante_id=entrega.estudiante_id,
        laboratorio_id=entrega.laboratorio_id,
        rubrica_version_id=entrega.rubrica_version_id,
        enlace_github=entrega.enlace_github,
        fecha=entrega.fecha,
        rubrica_version_numero=numero,
        evidencias=[
            EvidenciaArchivo(
                id=e.id,
                entrega_id=e.entrega_id,
                tipo=TipoEvidencia(e.tipo),
                nombre=e.nombre,
                sha256=e.sha256,
                tamano_bytes=e.tamano_bytes,
                resumen=e.resumen,
            )
            for e in ordenadas
        ],
    )


def armar_entregas(db: Db, entregas: list[EntregaFila]) -> list[Entrega]:
    """Las entregas con sus archivos y el número de rúbrica, en dos consultas (sin N+1).

    `texto_extraido` no se carga (la columna es diferida): puede pesar varios MB por archivo."""
    if not entregas:
        return []
    ids = [e.id for e in entregas]
    por_entrega: dict[uuid.UUID, list[EvidenciaFila]] = {i: [] for i in ids}
    for evidencia in db.scalars(select(EvidenciaFila).where(EvidenciaFila.entrega_id.in_(ids))):
        por_entrega[evidencia.entrega_id].append(evidencia)
    numeros = dict(
        db.execute(
            select(RubricaVersionFila.id, RubricaVersionFila.numero).where(
                RubricaVersionFila.id.in_({e.rubrica_version_id for e in entregas})
            )
        ).all()
    )
    return [a_esquema(e, por_entrega[e.id], numeros.get(e.rubrica_version_id)) for e in entregas]


def es_estudiante(usuario) -> bool:
    return usuario.rol == Rol.ESTUDIANTE.value


def negar_ajeno(db: Db, request: Request, usuario_id: uuid.UUID, entidad: str, entidad_id: uuid.UUID) -> None:
    """Deja en la auditoría que alguien pidió algo que no es suyo (OWASP A09).

    Para que nadie llene la tabla a golpe de clic: el mismo intento no se repite dentro de
    un minuto, y cada usuario deja como máximo AJENOS_POR_HORA filas por hora. Al llegar
    al tope queda UNA fila `acceso_ajeno_tope` (así se sabe que siguió intentando) y cada
    intento siguiente va al registro del servidor con lo que pidió.

    El conteo no va bajo bloqueo: en una ráfaga simultánea pueden entrar unas filas de más
    antes de que el tope corte. Se acepta (D-17)."""
    ip = seguridad.ip_de(request)
    if _contar_auditoria(db, usuario_id, "acceso_ajeno_denegado", timedelta(hours=1)) >= AJENOS_POR_HORA:
        registro.warning(
            "Intento ajeno por encima del tope: usuario %s, %s %s", usuario_id, entidad, entidad_id
        )
        if _contar_auditoria(db, usuario_id, "acceso_ajeno_tope", timedelta(hours=1)) == 0:
            registrar(db, usuario_id=usuario_id, accion="acceso_ajeno_tope", entidad=entidad, ip=ip)
            db.commit()
        return
    if _ya_anotado(db, usuario_id, "acceso_ajeno_denegado", entidad_id):
        return
    registrar(
        db,
        usuario_id=usuario_id,
        accion="acceso_ajeno_denegado",
        entidad=entidad,
        entidad_id=entidad_id,
        ip=ip,
    )
    db.commit()


def _contar_auditoria(db: Db, usuario_id: uuid.UUID, accion: str, ventana: timedelta) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Auditoria)
        .where(
            Auditoria.usuario_id == usuario_id,
            Auditoria.accion == accion,
            Auditoria.fecha >= seguridad.ahora() - ventana,
        )
    )


def _ya_anotado(db: Db, usuario_id: uuid.UUID, accion: str, entidad_id: uuid.UUID) -> bool:
    """¿La misma acción sobre el mismo id ya quedó en la auditoría en el último minuto?"""
    fila = db.scalar(
        select(Auditoria.id)
        .where(
            Auditoria.usuario_id == usuario_id,
            Auditoria.accion == accion,
            Auditoria.entidad_id == str(entidad_id),
            Auditoria.fecha >= seguridad.ahora() - timedelta(seconds=AUDITORIA_SIN_REPETIR_SEG),
        )
        .limit(1)
    )
    return fila is not None


# ---------- Topes por estudiante ----------


def _revisar_topes(
    db: Db,
    estudiante_id: uuid.UUID,
    laboratorio_id: uuid.UUID,
    *,
    sha_informe: str | None = None,
    bytes_nuevos: int = 0,
) -> None:
    """Lanza _TopeSuperado si el estudiante ya no puede entregar. Se llama dos veces: antes de
    trabajar (rápido) y justo antes de guardar, con su fila bloqueada (la que manda)."""
    ahora = seguridad.ahora()
    rechazos = db.scalar(
        select(func.count())
        .select_from(Auditoria)
        .where(
            Auditoria.usuario_id == estudiante_id,
            Auditoria.accion == "archivo_rechazado",
            Auditoria.fecha >= ahora - timedelta(hours=1),
        )
    )
    if rechazos >= RECHAZOS_POR_HORA:
        raise _TopeSuperado(status.HTTP_429_TOO_MANY_REQUESTS, MUCHOS_RECHAZOS)
    contar = select(func.count()).select_from(EntregaFila).where(EntregaFila.estudiante_id == estudiante_id)
    if db.scalar(contar.where(EntregaFila.fecha >= ahora - timedelta(hours=1))) >= ENTREGAS_POR_HORA:
        raise _TopeSuperado(status.HTTP_429_TOO_MANY_REQUESTS, MUCHAS_POR_HORA)
    if db.scalar(contar.where(EntregaFila.laboratorio_id == laboratorio_id)) >= ENTREGAS_POR_LABORATORIO:
        raise _TopeSuperado(status.HTTP_409_CONFLICT, MUCHAS_EN_LABORATORIO)
    if sha_informe is not None:
        repetida = db.scalar(
            select(EntregaFila.id)
            .where(
                EntregaFila.estudiante_id == estudiante_id,
                EntregaFila.laboratorio_id == laboratorio_id,
                EntregaFila.sha256_informe == sha_informe,
            )
            .limit(1)
        )
        if repetida is not None:
            raise _TopeSuperado(status.HTTP_409_CONFLICT, REPETIDA)
    if bytes_nuevos:
        hoy = db.scalar(
            select(func.coalesce(func.sum(EvidenciaFila.tamano_bytes), 0))
            .join(EntregaFila, EntregaFila.id == EvidenciaFila.entrega_id)
            .where(EntregaFila.estudiante_id == estudiante_id, EntregaFila.fecha >= ahora - timedelta(days=1))
        )
        if hoy + bytes_nuevos > MEGAS_POR_DIA * 1024 * 1024:
            raise _TopeSuperado(status.HTTP_429_TOO_MANY_REQUESTS, MUCHOS_MEGAS)


def _bloquear_estudiante(db: Db, estudiante_id: uuid.UUID) -> None:
    """Bloquea la fila del estudiante hasta el commit: sus subidas se guardan de a una
    (en PostgreSQL). Así el conteo de topes y el INSERT no se cruzan entre peticiones."""
    # key_share=True es FOR NO KEY UPDATE: pone en fila las subidas del estudiante sin
    # frenar las llaves foráneas (auditoría, sesiones) que apuntan a su fila.
    db.execute(select(Usuario.id).where(Usuario.id == estudiante_id).with_for_update(key_share=True))


# ---------- Procesar los archivos ----------


def _procesar(
    informe: bytes,
    nombre_informe: str | None,
    codigo: UploadFile | None,
    imagenes: list[UploadFile],
    diapos: UploadFile | None,
) -> list[_Archivo]:
    archivos: list[_Archivo] = []

    if not pdf.es_pdf(informe):
        raise ArchivoNoValido("Informe: debe ser un PDF.")
    try:
        lectura = pdf.leer_paginas(
            informe, maximo_paginas=MAXIMO_PAGINAS_INFORME, maximo_caracteres=MAXIMO_CARACTERES_INFORME
        )
    except ArchivoNoValido as error:
        raise ArchivoNoValido(f"Informe: {error}") from None
    if sum(len(p.strip()) for p in lectura.paginas) < MINIMO_CARACTERES_INFORME:
        raise ArchivoNoValido(ESCANEADO)
    archivos.append(
        _Archivo(
            TipoEvidencia.PDF,
            nombre_visible(nombre_informe, "informe.pdf"),
            informe,
            "application/pdf",
            {"paginas": lectura.paginas, "recortado": lectura.recortado},
            _resumen_paginas(lectura.paginas, "página", lectura.recortado),
        )
    )

    if codigo is not None:
        contenido = _leer(codigo, MAXIMO_CODIGO, "Código")
        try:
            extraido = lector_zip.leer_zip(contenido)
        except ArchivoNoValido as error:
            raise ArchivoNoValido(f"Código: {error}") from None
        archivos.append(
            _Archivo(
                TipoEvidencia.CODIGO,
                nombre_visible(codigo.filename, "codigo.zip"),
                contenido,
                "application/zip",
                extraido.como_json(),
                f"{_cuantos(len(extraido.archivos), 'archivo')} de código, "
                f"{_cuantos(len(extraido.omitidos), 'omitido')}",
            )
        )

    for i, imagen in enumerate(imagenes, start=1):
        contenido = _leer(imagen, MAXIMO_IMAGEN, f"Imagen {i}")
        mime = _tipo_imagen(contenido)
        if mime is None:
            raise ArchivoNoValido(f"Imagen {i}: debe ser PNG, JPG o WEBP.")
        archivos.append(
            _Archivo(
                TipoEvidencia.IMAGEN,
                nombre_visible(imagen.filename, f"imagen-{i}"),
                contenido,
                mime,
                None,
                "La IA la describe al evaluar",
            )
        )

    if diapos is not None:
        contenido = _leer(diapos, MAXIMO_DIAPOSITIVAS, "Diapositivas")
        try:
            formato, textos, recortado = diapositivas.leer_diapositivas(contenido)
        except ArchivoNoValido as error:
            raise ArchivoNoValido(f"Diapositivas: {error}") from None
        mime = (
            "application/pdf"
            if formato == "pdf"
            else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        archivos.append(
            _Archivo(
                TipoEvidencia.DIAPOSITIVAS,
                nombre_visible(diapos.filename, f"diapositivas.{formato}"),
                contenido,
                mime,
                {"paginas": textos, "formato": formato, "recortado": recortado},
                _resumen_paginas(textos, "diapositiva", recortado),
            )
        )
    return archivos


def _rechazar(db: Db, estudiante_id, laboratorio_id, ip, error: ArchivoNoValido, codigo: int):
    """Un archivo rechazado queda en la auditoría (solo el motivo, que es un texto nuestro).
    Esos rechazos cuentan para RECHAZOS_POR_HORA."""
    registrar(
        db,
        usuario_id=estudiante_id,
        accion="archivo_rechazado",
        entidad="laboratorio",
        entidad_id=laboratorio_id,
        detalle={"motivo": str(error)[:200]},
        ip=ip,
    )
    db.commit()
    return HTTPException(codigo, str(error))


def _es_informe_repetido(error: IntegrityError) -> bool:
    """PostgreSQL nombra la restricción; SQLite dice "UNIQUE constraint failed" y las columnas."""
    texto = str(error.orig)
    en_sqlite = "UNIQUE constraint failed" in texto and "sha256_informe" in texto
    return "uq_entregas_informe" in texto or en_sqlite


def _borrar(almacen: Almacen, rutas: list[str]) -> None:
    """Que no queden archivos sueltos sin entrega."""
    for ruta_archivo in rutas:
        try:
            almacen.borrar(ruta_archivo)
        except Exception:  # noqa: S110 (si falla la limpieza, se registra la ruta y se sigue)
            registro.warning("Archivo suelto sin entrega, borrarlo a mano: %s", ruta_archivo)


# ---------- Rutas ----------


@ruta(router, "POST", "/api/entregas", response_model=Entrega, status_code=status.HTTP_201_CREATED)
@limitador.limit(LIMITE_POR_USUARIO, key_func=seguridad.clave_de_usuario)
def subir_entrega(
    request: Request,
    actual: Actual,
    db: Db,
    almacen: AlmacenDep,
    laboratorio_id: Annotated[uuid.UUID, Form()],
    informe: Annotated[UploadFile, File(description="Informe en PDF con texto")],
    codigo: Annotated[UploadFile | None, File(description="Código en ZIP")] = None,
    enlace_github: Annotated[str | None, Form(max_length=200)] = None,
    imagenes: Annotated[list[UploadFile] | None, File(description="Hasta 5 imágenes")] = None,
    diapositivas_archivo: Annotated[
        UploadFile | None, File(alias="diapositivas", description="PPTX o PDF")
    ] = None,
) -> Entrega:
    enlace = (enlace_github or "").strip() or None
    try:
        EntregaCrear(laboratorio_id=laboratorio_id, enlace_github=enlace)
    except ValidationError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, ENLACE_MALO) from None
    if codigo is None and enlace is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, FALTA_CODIGO)
    imagenes = imagenes or []
    if len(imagenes) > MAXIMO_IMAGENES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Se aceptan hasta {MAXIMO_IMAGENES} imágenes."
        )

    buscar_laboratorio(db, laboratorio_id)
    try:
        version_id = versiones.version_evaluable(db, laboratorio_id).id
    except versiones.RubricaNoEvaluable:
        raise HTTPException(status.HTTP_409_CONFLICT, SIN_RUBRICA) from None
    estudiante_id = actual.id
    ip = seguridad.ip_de(request)
    try:
        _revisar_topes(db, estudiante_id, laboratorio_id)  # rápida: para no gastar trabajo
    except _TopeSuperado as tope:
        raise HTTPException(tope.codigo, str(tope)) from None
    db.rollback()  # leer los archivos puede tardar: se suelta la conexión mientras tanto

    if not _SUBIDAS.acquire(timeout=ESPERA_TURNO_SEG):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, OCUPADO)
    try:  # el turno cubre todo: leer, procesar y guardar
        return _subir_con_turno(
            db, almacen, estudiante_id, laboratorio_id, version_id, enlace, ip,
            informe, codigo, imagenes, diapositivas_archivo,
        )  # fmt: skip
    finally:
        _SUBIDAS.release()


def _subir_con_turno(
    db: Db,
    almacen: Almacen,
    estudiante_id: uuid.UUID,
    laboratorio_id: uuid.UUID,
    version_id: uuid.UUID,
    enlace: str | None,
    ip: str | None,
    informe: UploadFile,
    codigo: UploadFile | None,
    imagenes: list[UploadFile],
    diapos: UploadFile | None,
) -> Entrega:
    try:
        contenido_informe = _leer(informe, MAXIMO_INFORME, "Informe")
        sha_informe = hashlib.sha256(contenido_informe).hexdigest()
        try:
            _revisar_topes(db, estudiante_id, laboratorio_id, sha_informe=sha_informe)
        except _TopeSuperado as tope:
            raise HTTPException(tope.codigo, str(tope)) from None
        db.rollback()
        archivos = _procesar(contenido_informe, informe.filename, codigo, imagenes, diapos)
    except ArchivoMuyGrande as error:
        raise _rechazar(
            db, estudiante_id, laboratorio_id, ip, error, status.HTTP_413_CONTENT_TOO_LARGE
        ) from None
    except ArchivoNoValido as error:
        raise _rechazar(db, estudiante_id, laboratorio_id, ip, error, status.HTTP_400_BAD_REQUEST) from None

    entrega_id = uuid.uuid4()
    guardados: list[str] = []
    try:
        for archivo in archivos:
            ruta_archivo = almacenes.ruta_de(entrega_id, archivo.id)
            almacen.guardar(ruta_archivo, archivo.contenido, archivo.tipo_mime)
            guardados.append(ruta_archivo)

        # La revisión que manda: con el estudiante bloqueado, justo antes de guardar.
        _bloquear_estudiante(db, estudiante_id)
        _revisar_topes(
            db,
            estudiante_id,
            laboratorio_id,
            sha_informe=sha_informe,
            bytes_nuevos=sum(len(a.contenido) for a in archivos),
        )
        entrega = EntregaFila(
            id=entrega_id,
            estudiante_id=estudiante_id,
            laboratorio_id=laboratorio_id,
            rubrica_version_id=version_id,
            enlace_github=enlace,
            sha256_informe=sha_informe,
        )
        db.add(entrega)
        db.add_all(
            [
                EvidenciaFila(
                    id=a.id,
                    entrega_id=entrega_id,
                    tipo=a.tipo.value,
                    nombre=a.nombre,
                    sha256=a.sha256,
                    tamano_bytes=len(a.contenido),
                    tipo_mime=a.tipo_mime,
                    ruta_storage=almacenes.ruta_de(entrega_id, a.id),
                    texto_extraido=a.texto_extraido,
                    resumen=a.resumen,
                )
                for a in archivos
            ]
        )
        registrar(
            db,
            usuario_id=estudiante_id,
            accion="entrega_subida",
            entidad="entrega",
            entidad_id=entrega_id,
            detalle={
                "laboratorio_id": str(laboratorio_id),
                "rubrica_version_id": str(version_id),
                "enlace_github": enlace is not None,
                "archivos": [
                    {"tipo": a.tipo.value, "sha256": a.sha256, "tamano_bytes": len(a.contenido)}
                    for a in archivos
                ],
            },
            ip=ip,
        )
        db.commit()
    except _TopeSuperado as tope:
        db.rollback()
        _borrar(almacen, guardados)
        raise HTTPException(tope.codigo, str(tope)) from None
    except IntegrityError as error:
        db.rollback()
        _borrar(almacen, guardados)
        # Solo la restricción del informe es "ya lo subiste". Cualquier otra (por ejemplo un
        # NOT NULL) es un error de verdad: queda en el registro y sale como error genérico.
        if _es_informe_repetido(error):
            raise HTTPException(status.HTTP_409_CONFLICT, REPETIDA) from None
        registro.error(
            "Error de integridad al guardar la entrega %s: %s", entrega_id, type(error.orig).__name__
        )
        raise
    except Exception:
        db.rollback()
        _borrar(almacen, guardados)
        raise
    return armar_entregas(db, [entrega])[0]


Desde = Annotated[int, Query(ge=0, description="Cuántas saltar (para ver la página siguiente)")]
Limite = Annotated[int, Query(ge=1, le=LISTA_MAXIMA, description="Cuántas traer")]


@ruta(router, "GET", "/api/mis-entregas", response_model=list[Entrega])
def mis_entregas(
    actual: Actual, db: Db, desde: Desde = 0, limite: Limite = LISTA_POR_DEFECTO
) -> list[Entrega]:
    filas = db.scalars(
        select(EntregaFila)
        .where(EntregaFila.estudiante_id == actual.id)
        .order_by(EntregaFila.fecha.desc(), EntregaFila.id.desc())  # el id desempata: orden fijo
        .offset(desde)
        .limit(limite)
    ).all()
    return armar_entregas(db, list(filas))


def _entrega_visible(db: Db, request: Request, actual, entrega_id: uuid.UUID) -> EntregaFila:
    entrega = db.get(EntregaFila, entrega_id)
    if entrega is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    if es_estudiante(actual) and entrega.estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "entrega", entrega_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return entrega


@ruta(router, "GET", "/api/entregas/{entrega_id}", response_model=Entrega)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_entrega(request: Request, entrega_id: uuid.UUID, actual: Actual, db: Db) -> Entrega:
    return armar_entregas(db, [_entrega_visible(db, request, actual, entrega_id)])[0]


@ruta(router, "GET", "/api/laboratorios/{laboratorio_id}/entregas", response_model=list[Entrega])
def entregas_del_laboratorio(
    laboratorio_id: uuid.UUID, db: Db, desde: Desde = 0, limite: Limite = LISTA_POR_DEFECTO
) -> list[Entrega]:
    buscar_laboratorio(db, laboratorio_id)
    filas = db.scalars(
        select(EntregaFila)
        .where(EntregaFila.laboratorio_id == laboratorio_id)
        .order_by(EntregaFila.fecha.desc(), EntregaFila.id.desc())
        .offset(desde)
        .limit(limite)
    ).all()
    return armar_entregas(db, list(filas))


@ruta(router, "GET", "/api/evidencias/{evidencia_id}/enlace", response_model=EnlaceDescarga)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def enlace_de_descarga(
    request: Request, evidencia_id: uuid.UUID, actual: Actual, db: Db, almacen: AlmacenDep
) -> EnlaceDescarga:
    evidencia = db.get(EvidenciaFila, evidencia_id)
    if evidencia is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVIDENCIA_NO_EXISTE)
    entrega = db.get(EntregaFila, evidencia.entrega_id)
    if entrega is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVIDENCIA_NO_EXISTE)
    if es_estudiante(actual) and entrega.estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "evidencia", evidencia_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVIDENCIA_NO_EXISTE)
    url = almacen.enlace(evidencia.ruta_storage, evidencia.nombre)
    # Quién pidió bajar qué (OWASP A09). Solo ids: el enlace no se guarda. El mismo archivo
    # pedido otra vez dentro de un minuto no se vuelve a anotar, y cada usuario anota como
    # máximo ENLACES_POR_HORA por hora. Pasado el tope queda UNA fila `enlace_tope` por hora y
    # cada enlace siguiente va al registro del servidor como aviso (warning: el nivel info no
    # se imprime con la configuración por defecto, y así se perdía el rastro).
    if _contar_auditoria(db, actual.id, "enlace_emitido", timedelta(hours=1)) >= ENLACES_POR_HORA:
        registro.warning("Enlace por encima del tope: usuario %s, evidencia %s", actual.id, evidencia_id)
        if _contar_auditoria(db, actual.id, "enlace_tope", timedelta(hours=1)) == 0:
            registrar(
                db,
                usuario_id=actual.id,
                accion="enlace_tope",
                entidad="evidencia",
                ip=seguridad.ip_de(request),
            )
            db.commit()
    elif not _ya_anotado(db, actual.id, "enlace_emitido", evidencia_id):
        registrar(
            db,
            usuario_id=actual.id,
            accion="enlace_emitido",
            entidad="evidencia",
            entidad_id=evidencia_id,
            ip=seguridad.ip_de(request),
        )
        db.commit()
    return EnlaceDescarga(url=url, vence_en_seg=almacenes.VIGENCIA_ENLACE_SEG)


@ruta(router, "GET", "/api/archivos/{token}")
def bajar_archivo(token: str, almacen: AlmacenDep) -> Response:
    """Solo existe con el almacén local: en Supabase el enlace firmado lo sirve Supabase."""
    datos = almacenes.leer_token(token) if isinstance(almacen, AlmacenLocal) else None
    if datos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ENLACE_NO_VALIDO)
    try:
        contenido = almacen.leer(datos["ruta"])
    except (FileNotFoundError, ValueError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, ENLACE_NO_VALIDO) from None
    nombre = nombre_visible(str(datos["nombre"]), "archivo")
    return Response(
        content=contenido,
        media_type="application/octet-stream",  # se baja, nunca se abre dentro de la app
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"},
    )
