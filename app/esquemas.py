"""Contrato de datos del proyecto.

Aquí viven los modelos que comparten los módulos y los que validan la salida
de la IA. Todos los modelos tienen extra="forbid": si llega un campo que no
está aquí (por ejemplo una "nota"), se rechaza.

Las notas solo aparecen en modelos que arma el backend (Evaluacion,
EvaluacionPublicada, EvaluacionResumen, ResultadoLaboratorio). Ningún modelo
que llega de afuera (IA, docente, estudiante) tiene campo de nota.
"""

import os
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    IPvAnyAddress,
    StringConstraints,
    model_validator,
)

TOLERANCIA_PESOS = 0.01
NOTA_MINIMA = 0.0
NOTA_MAXIMA = 5.0

CONTRASENA_MINIMA = 10  # OWASP A07
CONTRASENA_MAXIMA_BYTES = 72  # bcrypt no acepta más

PATRON_CORREO = r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$"
PATRON_SHA256 = r"^[0-9a-f]{64}$"
PATRON_REPO_GITHUB = r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9._-]*/?$"

# Direcciones fijas de los proveedores en la nube (OWASP: evita mandar la llave a otro servidor)
URL_POR_PROVEEDOR = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
# Equipos donde puede estar Ollama; se cambia con la variable OLLAMA_HOSTS_PERMITIDOS
OLLAMA_HOSTS_POR_DEFECTO = "localhost,127.0.0.1"


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- Tipos con tope de tamaño (OWASP LLM10) ----------


def _cabe_en_bcrypt(valor: str) -> str:
    if len(valor.encode("utf-8")) > CONTRASENA_MAXIMA_BYTES:
        raise ValueError("La contraseña es demasiado larga.")
    return valor


def _en_minusculas(valor: Any) -> Any:
    """Ana@X.co y ana@x.co son la misma cuenta."""
    return valor.strip().lower() if isinstance(valor, str) else valor


def _nombre_seguro(valor: str) -> str:
    """Nombre o ruta relativa de un archivo de la entrega, sin trucos para salirse de la carpeta."""
    partes = valor.split("/")
    if "\\" in valor or ":" in valor or "\x00" in valor or valor.startswith("/") or ".." in partes:
        raise ValueError("El nombre del archivo no es válido.")
    return valor


# Las contraseñas no se recortan: los espacios también cuentan.
Contrasena = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=CONTRASENA_MAXIMA_BYTES),
    AfterValidator(_cabe_en_bcrypt),
]
ContrasenaNueva = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False, min_length=CONTRASENA_MINIMA, max_length=CONTRASENA_MAXIMA_BYTES
    ),
    AfterValidator(_cabe_en_bcrypt),
]
Correo = Annotated[
    str, BeforeValidator(_en_minusculas), StringConstraints(max_length=254, pattern=PATRON_CORREO)
]
NombreArchivo = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_nombre_seguro)]
Item = Annotated[str, Field(min_length=1, max_length=500)]
ListaCorta = Annotated[list[Item], Field(max_length=10)]
Justificacion = Annotated[str, Field(min_length=1, max_length=2000)]


# ---------- Listas cerradas ----------


class Rol(StrEnum):
    ESTUDIANTE = "estudiante"
    DOCENTE = "docente"
    ADMINISTRADOR = "administrador"


class EstadoEvaluacion(StrEnum):
    """Estados de una evaluación (SRS sección 6). Solo PUBLICADA la ve el estudiante."""

    EN_PROCESO = "en_proceso"
    EN_REVISION = "en_revision"
    REVISION_MANUAL = "revision_manual"
    APROBADA = "aprobada"
    PUBLICADA = "publicada"


class MotivoPrioridad(StrEnum):
    """Por qué una evaluación sube en la bandeja del docente (SRS sección 6)."""

    CITA_NO_ENCONTRADA = "cita_no_encontrada"
    ALERTA_INYECCION = "alerta_inyeccion"
    BAJA_COINCIDENCIA = "baja_coincidencia"
    SIN_PROPUESTA = "sin_propuesta"


class NivelDominio(StrEnum):
    ALTO = "Alto"
    MEDIO = "Medio"
    BASICO = "Básico"
    POR_FORTALECER = "Por fortalecer"


class TipoEvidencia(StrEnum):
    PDF = "pdf"
    CODIGO = "codigo"
    IMAGEN = "imagen"
    DIAPOSITIVAS = "diapositivas"
    VIDEO = "video"


class TipoVerificacion(StrEnum):
    SINTAXIS = "sintaxis"
    ESTATICO = "estatico"
    PRUEBAS = "pruebas"


class AccionRevision(StrEnum):
    AJUSTAR_NIVEL = "ajustar_nivel"
    EDITAR_RETROALIMENTACION = "editar_retroalimentacion"
    APROBAR = "aprobar"
    PUBLICAR = "publicar"


class OrigenRubrica(StrEnum):
    """De dónde salió una versión de la rúbrica. Las de archivo (salvo JSON) pasan por la IA."""

    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"
    TEXTO = "texto"
    EDITOR = "editor"


class ProveedorIA(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


class TipoNodo(StrEnum):
    CATEGORIA = "categoria"
    TEMA = "tema"
    LABORATORIO = "laboratorio"


# ---------- Usuarios (RF-01, RF-02) ----------


class Credenciales(Estricto):
    correo: Correo
    contrasena: Contrasena


class UsuarioCrear(Estricto):
    nombre: str = Field(min_length=1, max_length=120)
    correo: Correo
    contrasena: ContrasenaNueva
    rol: Rol


class UsuarioEditar(Estricto):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    rol: Rol | None = None
    activo: bool | None = None


class CambioContrasena(Estricto):
    """Cada usuario cambia su propia contraseña; así el administrador no la conoce."""

    actual: Contrasena
    nueva: ContrasenaNueva


class ClaveTemporal(Estricto):
    """El administrador le pone una clave temporal a quien olvidó la suya o quedó bloqueado."""

    contrasena: ContrasenaNueva


class UsuarioPublico(Estricto):
    """Lo único de un usuario que sale del backend. Nunca lleva la contraseña."""

    id: UUID
    nombre: str
    correo: str
    rol: Rol
    activo: bool
    foto_url: str | None = None


class MiSesion(Estricto):
    """Lo que recibe el navegador al entrar y en `GET /api/yo`."""

    usuario: UsuarioPublico
    debe_cambiar_contrasena: bool


# ---------- Cohortes y laboratorios (RF-03) ----------


class CohorteCrear(Estricto):
    nombre: str = Field(min_length=1, max_length=80)
    periodo: str = Field(min_length=1, max_length=40)


class Cohorte(CohorteCrear):
    id: UUID


class LaboratorioCrear(Estricto):
    cohorte_id: UUID
    titulo: str = Field(min_length=1, max_length=160)
    descripcion: str = Field(min_length=1, max_length=5000)
    objetivos: str = Field(min_length=1, max_length=5000)
    temas_ia: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=30
    )


class Laboratorio(LaboratorioCrear):
    id: UUID


class LaboratorioEditar(Estricto):
    """Solo cambia lo que venga. La cohorte no se cambia: las entregas ya cuelgan de ella."""

    titulo: str | None = Field(default=None, min_length=1, max_length=160)
    descripcion: str | None = Field(default=None, min_length=1, max_length=5000)
    objetivos: str | None = Field(default=None, min_length=1, max_length=5000)
    temas_ia: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = Field(
        default=None, max_length=30
    )


# ---------- Rúbricas ----------


class Nivel(Estricto):
    id: str = Field(min_length=1, max_length=40)
    nombre: str = Field(min_length=1, max_length=120)
    descriptor: str = Field(max_length=1000)
    valor: float = Field(ge=0, le=100, allow_inf_nan=False)


class Criterio(Estricto):
    id: str = Field(min_length=1, max_length=40)
    nombre: str = Field(min_length=1, max_length=200)
    competencia: str = Field(max_length=200)
    # Peso 0 y un solo nivel se aceptan aquí para que una rúbrica incompleta se pueda
    # guardar y corregir en el editor; `validar_rubrica` los marca como error (RF-05).
    peso: float = Field(ge=0, le=100, allow_inf_nan=False, description="Porcentaje; todos suman 100")
    niveles: list[Nivel] = Field(min_length=1, max_length=10)

    @property
    def valor_maximo(self) -> float:
        return max(n.valor for n in self.niveles)


class RubricaEstructura(Estricto):
    laboratorio: str = Field(max_length=200)
    criterios: list[Criterio] = Field(min_length=1, max_length=30)


def validar_rubrica(rubrica: RubricaEstructura) -> list[str]:
    """Devuelve la lista de errores de la rúbrica. Lista vacía = válida (RF-05)."""
    errores: list[str] = []

    suma = sum(c.peso for c in rubrica.criterios)
    if abs(suma - 100) > TOLERANCIA_PESOS:
        errores.append(f"Los pesos suman {suma:g} %, deben sumar 100 %.")

    ids = [c.id for c in rubrica.criterios]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        errores.append(f"Criterios con id repetido: {', '.join(repetidos)}.")

    for c in rubrica.criterios:
        if c.peso <= 0:
            errores.append(f"El criterio '{c.nombre}' no tiene peso.")
        if len(c.niveles) < 2:
            errores.append(f"El criterio '{c.nombre}' necesita al menos 2 niveles.")
        ids_niveles = [n.id for n in c.niveles]
        if len(set(ids_niveles)) != len(ids_niveles):
            errores.append(f"El criterio '{c.nombre}' tiene niveles con id repetido.")
        valores = [n.valor for n in c.niveles]
        sube = all(a < b for a, b in zip(valores, valores[1:], strict=False))
        baja = all(a > b for a, b in zip(valores, valores[1:], strict=False))
        if not (sube or baja):
            errores.append(
                f"Los niveles del criterio '{c.nombre}' no están en orden: "
                "sus valores deben ir de menor a mayor (o de mayor a menor) sin repetirse."
            )
        if len(c.niveles) >= 2 and c.valor_maximo <= 0:
            errores.append(f"El criterio '{c.nombre}' no tiene ningún nivel con valor mayor a 0.")
        sin_descriptor = [n.nombre for n in c.niveles if not n.descriptor]
        if sin_descriptor:
            errores.append(
                f"El criterio '{c.nombre}' tiene niveles sin descriptor: {', '.join(sin_descriptor)}."
            )
        if not c.competencia:
            errores.append(f"El criterio '{c.nombre}' no tiene competencia asociada.")

    return errores


class RubricaVersion(Estricto):
    """Una versión guardada de la rúbrica (RF-06). No se edita: se crea la siguiente."""

    id: UUID
    rubrica_id: UUID
    numero: int = Field(ge=1)
    estructura: RubricaEstructura
    valida: bool
    errores: list[str]
    origen: OrigenRubrica
    # La convirtió la IA y el docente todavía no la revisa: no sirve para evaluar (D-16).
    por_confirmar: bool = False
    prompt_version: str | None = None  # solo si pasó por la IA
    creada_por: UUID
    fecha: datetime


class RubricaPublica(Estricto):
    """Lo que ve el estudiante de la rúbrica: solo la estructura de la última versión lista."""

    numero: int = Field(ge=1)
    estructura: RubricaEstructura
    fecha: datetime


# ---------- Salidas de la IA (RF-11 y SRS sección 9) ----------


class Evidencia(Estricto):
    archivo: NombreArchivo = Field(description='Ej. "informe.pdf" o "src/agente.py"')
    ubicacion: str = Field(min_length=1, max_length=80, description='Ej. "página 4" o "líneas 20-35"')
    fragmento: str = Field(min_length=1, max_length=300, description="Texto copiado tal cual")


class ResultadoCriterio(Estricto):
    criterio_id: str = Field(min_length=1, max_length=40)
    nivel_id: str = Field(min_length=1, max_length=40)
    justificacion: Justificacion
    evidencias: list[Evidencia] = Field(min_length=1, max_length=10)
    fortalezas: ListaCorta
    debilidades: ListaCorta
    recomendaciones: ListaCorta
    # A propósito NO hay campo de nota: la IA no la calcula.


class TemaSugerido(Estricto):
    categoria: str = Field(min_length=1, max_length=80)
    tema: str = Field(min_length=1, max_length=80)


class TemasSugeridos(Estricto):
    """Temas de IA que la IA propone para un laboratorio; el docente los confirma."""

    temas: list[TemaSugerido] = Field(min_length=1, max_length=30)


class AccionFortalecimiento(Estricto):
    tema: str = Field(min_length=1, max_length=80)
    que_hacer: Item
    recursos: ListaCorta


class PlanFortalecimiento(Estricto):
    """Plan que redacta la IA con datos ya calculados por el backend. Sin notas."""

    resumen: Justificacion
    acciones: list[AccionFortalecimiento] = Field(min_length=1, max_length=10)


# ---------- Entregas y evidencias (RF-07, RF-08) ----------


class EntregaCrear(Estricto):
    """Datos de la entrega. Los archivos (PDF, ZIP, imágenes) llegan aparte, como archivos."""

    laboratorio_id: UUID
    enlace_github: str | None = Field(default=None, pattern=PATRON_REPO_GITHUB, max_length=200)


class EvidenciaArchivo(Estricto):
    id: UUID
    entrega_id: UUID
    tipo: TipoEvidencia
    nombre: NombreArchivo
    sha256: str = Field(pattern=PATRON_SHA256)


class Entrega(Estricto):
    id: UUID
    estudiante_id: UUID
    laboratorio_id: UUID
    rubrica_version_id: UUID
    enlace_github: str | None = Field(default=None, pattern=PATRON_REPO_GITHUB, max_length=200)
    evidencias: list[EvidenciaArchivo]
    fecha: datetime


# ---------- Evaluaciones (RF-10 a RF-15, RNF-08) ----------


class EvidenciaVerificada(Evidencia):
    """Cita de la IA ya buscada en el material (RF-12). None = aún sin verificar."""

    encontrada: bool | None = None


class VerificacionCodigo(Estricto):
    """Un resultado del sandbox (RF-10). El sandbox recorta la salida antes de guardarla."""

    tipo: TipoVerificacion
    comando: str = Field(max_length=500)
    codigo_salida: int | None
    salida: str = Field(max_length=20000)
    duracion_ms: int = Field(ge=0)
    tiempo_agotado: bool


class CriterioEvaluado(Estricto):
    """Un criterio dentro de una evaluación, como lo ve el docente.

    nivel_ia es None cuando la IA falló y el criterio quedó "Sin propuesta".
    """

    criterio_id: str = Field(min_length=1, max_length=40)
    nivel_ia: str | None
    nivel_final: str | None
    justificacion: str = Field(max_length=2000)
    evidencias: list[EvidenciaVerificada] = Field(max_length=10)
    fortalezas: ListaCorta
    debilidades: ListaCorta
    recomendaciones: ListaCorta


class Evaluacion(Estricto):
    """Evaluación completa. Solo para el docente.

    Las notas las escribe el backend con app/evaluador/nota.py; no hay ningún
    modelo de entrada que permita mandarlas.
    """

    id: UUID
    entrega_id: UUID
    rubrica_version_id: UUID
    estado: EstadoEvaluacion
    proveedor: ProveedorIA
    modelo: str
    version_prompt: str
    criterios: list[CriterioEvaluado]
    verificaciones: list[VerificacionCodigo]
    nota_preliminar: float | None = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    nota_final: float | None = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    tokens_entrada: int = Field(ge=0)
    tokens_salida: int = Field(ge=0)
    costo_usd: float = Field(ge=0, allow_inf_nan=False)
    alerta_inyeccion: bool
    fecha: datetime
    aprobada_por: UUID | None = None
    fecha_aprobacion: datetime | None = None
    fecha_publicacion: datetime | None = None


class EvaluacionResumen(Estricto):
    """Una fila de la bandeja del docente, con el motivo por el que va primero."""

    id: UUID
    entrega_id: UUID
    laboratorio_id: UUID
    estudiante_id: UUID
    estado: EstadoEvaluacion
    nota_preliminar: float | None = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    motivos: list[MotivoPrioridad]
    fecha: datetime


class CriterioPublicado(Estricto):
    criterio_id: str
    nivel_id: str
    justificacion: str
    evidencias: list[Evidencia]
    fortalezas: list[str]
    debilidades: list[str]
    recomendaciones: list[str]


class EvaluacionPublicada(Estricto):
    """Lo único que ve el estudiante (RNF-09): sin borradores de la IA ni datos internos."""

    id: UUID
    entrega_id: UUID
    laboratorio_id: UUID
    nota_final: float = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    criterios: list[CriterioPublicado]
    fecha_publicacion: datetime


# ---------- Revisión del docente (RF-14) ----------


class AjusteNivel(Estricto):
    """El docente cambia el nivel de un criterio. La nota la recalcula el backend."""

    criterio_id: str = Field(min_length=1, max_length=40)
    nivel_id: str = Field(min_length=1, max_length=40)
    justificacion: Justificacion


class AjusteRetroalimentacion(Estricto):
    criterio_id: str = Field(min_length=1, max_length=40)
    fortalezas: ListaCorta
    debilidades: ListaCorta
    recomendaciones: ListaCorta


class RevisionDocente(Estricto):
    """Una acción del docente sobre una evaluación, con el valor anterior y el nuevo."""

    id: UUID
    evaluacion_id: UUID
    docente_id: UUID
    accion: AccionRevision
    criterio_id: str | None = None
    valor_anterior: str | None = None
    valor_nuevo: str | None = None
    justificacion: str | None = None
    fecha: datetime


class TrazaEvaluacion(Estricto):
    """Lo que pide RNF-08 para la pestaña "Traza": con qué y quién se evaluó.

    No lleva la nota ni el texto de cada criterio.
    """

    evaluacion_id: UUID
    rubrica_version_id: UUID
    proveedor: ProveedorIA
    modelo: str
    version_prompt: str
    evidencias: list[EvidenciaArchivo]
    verificaciones: list[VerificacionCodigo]
    tokens_entrada: int = Field(ge=0)
    tokens_salida: int = Field(ge=0)
    alerta_inyeccion: bool
    fecha: datetime
    aprobada_por: UUID | None
    fecha_aprobacion: datetime | None
    fecha_publicacion: datetime | None
    revisiones: list[RevisionDocente]


# ---------- Informe integrado y mapa mental (RF-16, RF-17) ----------


class ResultadoLaboratorio(Estricto):
    laboratorio_id: UUID
    titulo: str
    cohorte: str
    nota_final: float = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    nivel: NivelDominio
    fecha_publicacion: datetime


class DominioTema(Estricto):
    categoria: str
    tema: str
    promedio: float = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    nivel: NivelDominio
    laboratorios: list[UUID]


class Informe(Estricto):
    """Informe integrado. Los números los calcula el backend; la IA solo redacta el plan."""

    estudiante_id: UUID
    nombre_estudiante: str
    laboratorios: list[ResultadoLaboratorio]
    promedio_general: float | None = Field(ge=NOTA_MINIMA, le=NOTA_MAXIMA, allow_inf_nan=False)
    temas: list[DominioTema]
    brechas: list[str]
    plan: PlanFortalecimiento | None
    generado: datetime


class NodoMapa(Estricto):
    id: str = Field(min_length=1)
    tipo: TipoNodo
    etiqueta: str = Field(min_length=1)
    nivel: NivelDominio | None = None
    evidencias: list[Evidencia] = Field(default_factory=list)
    que_profundizar: list[str] = Field(default_factory=list)


class AristaMapa(Estricto):
    origen: str = Field(min_length=1)
    destino: str = Field(min_length=1)


class MapaMental(Estricto):
    """Mapa categoría → tema → laboratorio, listo para Cytoscape.js."""

    estudiante_id: UUID
    nodos: list[NodoMapa]
    aristas: list[AristaMapa]


# ---------- Configuración de IA (RF-19) y auditoría (OWASP A09) ----------


class ConfigIA(Estricto):
    """Proveedor y modelo. La llave NO va aquí: vive en la variable LLM_API_KEY.

    La dirección no es libre: OpenAI y OpenRouter tienen una sola dirección
    permitida, y Ollama solo puede estar en los equipos de OLLAMA_HOSTS_PERMITIDOS.
    Así nadie puede hacer que el backend mande la llave a otro servidor.
    """

    proveedor: ProveedorIA
    modelo: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _direccion_permitida(self) -> Self:
        try:
            partes = urlsplit(self.base_url)
            host = partes.hostname
            partes.port  # noqa: B018  (lanza ValueError si el puerto no es un número)
        except ValueError as error:
            raise ValueError("La dirección del proveedor no es válida.") from error

        if partes.scheme not in {"http", "https"} or not host:
            raise ValueError("La dirección debe empezar por http:// o https://.")
        if partes.username or partes.password or partes.query or partes.fragment or "@" in partes.netloc:
            raise ValueError("La dirección no puede llevar usuario, clave ni parámetros.")

        fija = URL_POR_PROVEEDOR.get(self.proveedor.value)
        if fija is not None:
            if self.base_url.rstrip("/") != fija:
                raise ValueError(f"Para {self.proveedor.value} la dirección debe ser {fija}.")
        else:
            permitidos = os.environ.get("OLLAMA_HOSTS_PERMITIDOS", OLLAMA_HOSTS_POR_DEFECTO)
            if host not in {h.strip().lower() for h in permitidos.split(",") if h.strip()}:
                raise ValueError("Ese equipo no está en la lista de equipos permitidos para Ollama.")
        return self


class RegistroAuditoria(Estricto):
    """Una fila de la auditoría. Los secretos se frenan al guardar, en app/auditoria/registro.py."""

    id: UUID
    usuario_id: UUID | None
    accion: str = Field(min_length=1)
    entidad: str = Field(min_length=1)
    entidad_id: str | None = None
    detalle: dict[str, Any] = Field(default_factory=dict)
    ip: IPvAnyAddress | None = None
    fecha: datetime
