"""Ajustes de la app. Todo sale de variables de entorno (en el PC, del archivo .env)."""

import secrets
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETO_MINIMO = 32
# Variables con secretos. En modo proceso se sacan de os.environ al arrancar, después de
# leerlas, para que ningún proceso hijo las herede (app.sandbox.preparar_proceso_web, D-18).
SECRETOS_DEL_ENTORNO = frozenset(
    {"LLM_API_KEY", "SUPABASE_SERVICE_KEY", "JWT_SECRETO", "DATABASE_URL", "PRUEBAS_DATABASE_URL"}
)


class Ajustes(BaseSettings):
    # hide_input_in_errors: si un ajuste está mal, el error (que sale en el registro de Render)
    # no repite los valores, que traen las llaves.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # Lista cerrada: si ENTORNO queda mal escrito la app no arranca, en vez de
    # arrancar sin avisar en modo desarrollo (cookie sin HTTPS).
    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"
    database_url: str = ""
    jwt_secreto: str = ""
    origenes_permitidos: str = "http://localhost:5173"
    sesion_minutos: int = Field(default=480, ge=5, le=1440)
    bcrypt_rondas: int = Field(default=12, ge=4, le=15)

    # IA (RF-19). La llave es SecretStr para que no salga si alguien imprime los ajustes.
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_tiempo_seg: int = Field(default=60, ge=5, le=300)
    # Cuánto "razona" un modelo de OpenAI antes de responder (reasoning_effort). "low" gasta
    # poco; "none" desactiva el razonamiento. Vacío = no se manda (otros proveedores).
    llm_esfuerzo: Literal["", "none", "low", "medium", "high"] = "low"
    # Precio por millón de tokens del modelo (para el panel de costos, RF-20). Vacío = 0.
    llm_precio_entrada_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    llm_precio_salida_usd: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("llm_precio_entrada_usd", "llm_precio_salida_usd", mode="before")
    @classmethod
    def _precio_vacio(cls, valor: object) -> object:
        return 0 if valor in ("", None) else valor

    # Archivos de las entregas (RNF-07). En el PC, una carpeta; en Render, Supabase Storage
    # (el disco de Render se borra en cada despliegue).
    almacen: Literal["local", "supabase"] = "local"
    almacen_carpeta: str = "almacen_local"
    supabase_url: str = ""
    supabase_service_key: SecretStr = SecretStr("")
    supabase_bucket: str = Field(default="evidencias", pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")

    # Sandbox (RF-10, RNF-03, D-18). docker en el PC; proceso en Render (sin Docker adentro).
    sandbox_mode: Literal["docker", "proceso"] = "docker"
    sandbox_tiempo_seg: int = Field(default=60, ge=1, le=300)
    sandbox_memoria_mb: int = Field(default=256, ge=64, le=2048)
    # Sin "-" al inicio: el nombre va en la línea de `docker run` y no puede colarse como opción.
    sandbox_imagen: str = Field(
        default="asesor-sandbox:1", pattern=r"^[a-z0-9][a-z0-9._/-]{0,127}:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$"
    )
    # Ejecutar las pruebas del estudiante. En Render va en false: el aislamiento por proceso
    # es más débil que un contenedor (SRS sección 10, D-18).
    sandbox_pruebas: bool = True

    @property
    def en_produccion(self) -> bool:
        return self.entorno == "produccion"

    @property
    def origenes(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.origenes_permitidos.split(",") if o.strip()]

    @model_validator(mode="after")
    def _revisar(self) -> Self:
        # SQLAlchemy necesita saber qué conector usar; Supabase entrega la dirección sin él.
        for prefijo in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefijo):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefijo) :]

        if self.en_produccion:
            if len(self.jwt_secreto) < SECRETO_MINIMO:
                raise ValueError(
                    f"JWT_SECRETO debe tener al menos {SECRETO_MINIMO} caracteres en producción."
                )
            if not self.database_url:
                raise ValueError("Falta DATABASE_URL en producción.")
            if not self.origenes or any(not o.startswith("https://") for o in self.origenes):
                raise ValueError(
                    "En producción ORIGENES_PERMITIDOS debe ser la dirección https de la app (sin * ni http)."
                )
            if self.sandbox_mode == "proceso" and self.sandbox_pruebas:
                # Sin contenedor, el código del estudiante correría junto a la app (D-18).
                raise ValueError("En producción con SANDBOX_MODE=proceso, SANDBOX_PRUEBAS debe ser false.")
        elif not self.jwt_secreto:
            # En el PC, sin secreto, se inventa uno: las sesiones duran hasta que se reinicia la app.
            self.jwt_secreto = secrets.token_urlsafe(48)
        return self


@lru_cache
def ajustes() -> Ajustes:
    return Ajustes()
